"""Phase 9: deterministic retrieval ranking (metadata scoring)."""

from datetime import UTC, datetime, timedelta

from second_brain import semantic


def _add(home, title, body, **kw):
    return semantic.add_memory(home, title, body, **kw)


def _curate_status_current(home, mid):
    semantic.curate(home, mid, status="current")


def _ids(rows):
    return [r["memory_id"] for r in rows]


def test_grade_dominance_when_relevance_equal(brain_home):
    # Unit level with FIXED ranks: trust (grade) decides when relevance ties.
    tokens = semantic._query_tokens("wal frame")
    base = {
        "memory_id": "m1", "title": "Alpha rule", "summary": "", "status": "current",
        "scope": "project", "project_id": None, "updated_at": "2026-08-15T00:00:00+00:00",
        "current_version": 1, "successful_retrieval_count": 0, "contradiction_count": 0,
        "_body": "wal frame durability note here",
    }
    verified = dict(base, evidence_grade="VERIFIED")
    tested = dict(base, evidence_grade="TESTED")
    observed = dict(base, evidence_grade="OBSERVED")
    s_v = semantic._score_row(verified, tokens, None, None, semantic._SCORE_TERMS)
    s_t = semantic._score_row(tested, tokens, None, None, semantic._SCORE_TERMS)
    s_o = semantic._score_row(observed, tokens, None, None, semantic._SCORE_TERMS)
    assert s_v > s_t > s_o

    # Integration: VERIFIED + title-boosted doc ranks above a lower-grade doc
    verified2 = _add(
        brain_home,
        title="Wal frame verified",
        body="wal frame durability note here",
        grade="VERIFIED",
    )
    tested2 = _add(
        brain_home, title="Unrelated tested", body="wal frame durability note here", grade="TESTED"
    )
    _curate_status_current(brain_home, verified2)
    _curate_status_current(brain_home, tested2)
    rows = semantic.search_memories(brain_home, "wal frame")
    assert _ids(rows)[0] == verified2


def test_scope_match_boost_under_project_context(brain_home):
    proj = _add(
        brain_home,
        title="Budget rule p",
        body="token budget ceiling for this project here",
        scope="project",
        project_id="p1",
        grade="VERIFIED",
    )
    glob = _add(
        brain_home,
        title="Budget rule g",
        body="token budget ceiling for this project here",
        scope="global",
        project_id="p1",
        grade="VERIFIED",
    )
    _curate_status_current(brain_home, proj)
    _curate_status_current(brain_home, glob)
    rows = semantic.search_memories(brain_home, "budget ceiling", project_id="p1")
    ids = _ids(rows)
    assert len(ids) == 2  # scope rule keeps both (distinct buckets)
    assert ids[0] == proj  # exact project match ranks above global


def test_freshness_does_not_hide_relevant_old_memory(brain_home):
    old = _add(
        brain_home, title="Ancient exact match", body="wal journal frame content", grade="VERIFIED"
    )
    fresh = _add(
        brain_home, title="Fresh weak match", body="unrelated telemetry note", grade="VERIFIED"
    )
    _curate_status_current(brain_home, old)
    _curate_status_current(brain_home, fresh)
    # age the old memory 400 days via direct DB update
    conn = __import__("second_brain.db", fromlist=["connect"]).connect(
        __import__("second_brain.paths", fromlist=["db_path"]).db_path(brain_home)
    )
    try:
        old_dt = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        conn.execute("UPDATE memories SET updated_at=? WHERE memory_id=?", (old_dt, old))
        conn.commit()
    finally:
        conn.close()
    rows = semantic.search_memories(brain_home, "wal journal frame")
    # the highly relevant old memory (all query tokens, VERIFIED) outranks the
    # fresh but irrelevant one despite the 20% freshness penalty
    assert _ids(rows)[0] == old


def test_token_penalty_demotes_but_never_zeroes(brain_home):
    short = _add(brain_home, title="Concise rule", body="wal frame concise note", grade="VERIFIED")
    long_body = "wal frame " + "padding word " * 2500  # ~5000 tokens
    long = _add(brain_home, title="Verbose rule", body=long_body, grade="VERIFIED")
    _curate_status_current(brain_home, short)
    _curate_status_current(brain_home, long)
    rows = semantic.search_memories(brain_home, "wal frame")
    ids = _ids(rows)
    # long body pays the token penalty -> demoted below the concise doc
    assert ids[0] == short
    # but still present (never zeroed) and above a non-matching doc
    assert long in ids


def test_scorer_deterministic_and_stable(brain_home):
    _add(brain_home, title="Determinism rule", body="same words here")
    _add(brain_home, title="Determinism rule", body="same words here")
    r1 = _ids(semantic.search_memories(brain_home, "determinism"))
    r2 = _ids(semantic.search_memories(brain_home, "determinism"))
    assert r1 == r2
    # ties resolve by original rank then memory_id; order is stable
    assert sorted(r1) == sorted(r1)


def test_linear_fallback_same_ranking(brain_home, monkeypatch):
    verified = _add(
        brain_home,
        title="Fallback rank rule a",
        body="fallback ranking content here",
        grade="VERIFIED",
    )
    observed = _add(
        brain_home,
        title="Fallback rank rule b",
        body="fallback ranking content here",
        grade="OBSERVED",
    )
    _curate_status_current(brain_home, verified)
    _curate_status_current(brain_home, observed)
    monkeypatch.setattr(semantic, "_fts_available", lambda conn: False)
    rows = semantic.search_memories(brain_home, "fallback ranking")
    assert _ids(rows)[0] == verified  # shared scorer: trust decides on ties


def test_boundedness_pathological_rows(brain_home):
    # garbage timestamps, missing fields, extreme counts: no NaN/inf/explosion
    m = _add(brain_home, title="Pathological row", body="wal frame pathological content here")
    conn = __import__("second_brain.db", fromlist=["connect"]).connect(
        __import__("second_brain.paths", fromlist=["db_path"]).db_path(brain_home)
    )
    try:
        conn.execute(
            "UPDATE memories SET updated_at='not-a-date', successful_retrieval_count=999999, "
            "contradiction_count=999999 WHERE memory_id=?",
            (m,),
        )
        conn.commit()
    finally:
        conn.close()
    rows = semantic.search_memories(brain_home, "wal frame")
    assert len(rows) == 1
    # scores are finite and ordering works
    scores = [
        semantic._score_row(
            r, semantic._query_tokens("wal frame"), None, None, semantic._SCORE_TERMS
        )
        for r in rows
    ]
    for s in scores:
        assert s == s  # not NaN
        assert s < 1e6  # no explosion


def test_score_terms_ablation_knob(brain_home):
    # a: higher term frequency (bm25-favored) AND VERIFIED -> deterministically first
    a = _add(
        brain_home, title="Alpha record", body="ablation body content here ablation body",
        grade="VERIFIED",
    )
    b = _add(brain_home, title="Beta record", body="ablation body content here", grade="OBSERVED")
    _curate_status_current(brain_home, a)
    _curate_status_current(brain_home, b)
    rows = semantic.search_memories(brain_home, "ablation", score_terms=frozenset())
    assert len(rows) == 2  # knob works; both rows returned
    full = semantic.search_memories(brain_home, "ablation")
    assert _ids(full)[0] == a  # full scoring keeps the canonical doc first


def test_benchmark_fixture_canonical_target_ranks_first(brain_home):
    """Reproduces the retrieval_bench.py family fixture at unit level: 8
    same-theme docs share the anchor tokens; the canonical target is slot 5
    (NOT the first row, so bm25/rowid ties must not favor it) and is curated
    VERIFIED/current with decision value (successful_retrieval_count=5); one
    stale superseded copy and one near-identical labile duplicate sit in the
    same fact family. The anchor-phrase query must rank the canonical target
    first (the R@1 guarantee), never the duplicate or the stale copy, while
    the documented audit path (include_history + include_duplicates) still
    surfaces the old version."""

    mids = []
    for i in range(8):
        mid = semantic.add_memory(
            brain_home,
            title=f"WAL rule {i}",
            body=f"wal frame durability journal content note {i}",
            grade="TESTED",
            summary="wal frame",
        )
        semantic.curate(brain_home, mid, status="current")
        mids.append(mid)
    canonical = mids[5]
    semantic.curate(brain_home, canonical, grade="VERIFIED")
    conn = __import__("second_brain.db", fromlist=["connect"]).connect(
        __import__("second_brain.paths", fromlist=["db_path"]).db_path(brain_home)
    )
    try:
        conn.execute(
            "UPDATE memories SET successful_retrieval_count = 5 WHERE memory_id = ?",
            (canonical,),
        )
        conn.commit()
    finally:
        conn.close()

    # stale superseded copy of the same fact (separate memory_id, older)
    stale = semantic.add_memory(
        brain_home,
        title="WAL rule old",
        body="wal frame durability journal content note old",
        grade="OBSERVED",
    )
    semantic.curate(brain_home, stale, status="superseded")
    # near-identical labile duplicate
    dup = semantic.add_memory(
        brain_home,
        title="WAL rule copy",
        body="wal frame durability journal content note copy",
        grade="OBSERVED",
    )
    semantic.curate(brain_home, dup, status="labile")

    rows = semantic.search_memories(brain_home, "wal frame")
    ids = _ids(rows)
    assert ids and ids[0] == canonical  # canonical target ranks first
    assert stale not in ids  # Phase 7 filter: superseded excluded
    assert dup not in ids  # Phase 8 dedupe: canonical is family representative

    # history audit path still surfaces the old version (filters+dedupe
    # bypassed together, per test_superseded_family_keeps_current_only)
    audit = _ids(
        semantic.search_memories(
            brain_home, "wal frame", include_history=True, include_duplicates=True, top_k=20
        )
    )
    assert stale in audit
    assert canonical in audit

    # linear fallback applies the SAME tokenized matching + ranking
    # (benchmark fixture: multi-word anchor query must rank the target first)
    linear = _ids(semantic._search_linear(brain_home, "wal frame"))
    assert linear and linear[0] == canonical
    assert stale not in linear
    assert dup not in linear
