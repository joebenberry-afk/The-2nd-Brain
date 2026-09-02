"""Focused tests for the T1.1 IDF query builder and capsule query source."""

from second_brain import autoinject, db, semantic, working_set


def _add(home, title, body, **kwargs):
    return semantic.add_memory(home, title, body, **kwargs)


def test_query_uses_top_idf_terms_not_all_tokens(brain_home):
    """A bounded query keeps rare/high-IDF terms instead of every prompt token."""
    _add(
        brain_home,
        "Common",
        "common alpha bravo charlie delta echo foxtrot golf hotel indigo",
    )
    _add(brain_home, "Rare", "common alpha bravo charlie delta echo foxtrot juliett")
    conn = db.connect(db.db_path(brain_home))
    try:
        query = semantic.build_query(
            "common alpha bravo charlie delta echo foxtrot golf hotel indigo juliett",
            k=8,
            conn=conn,
        )
    finally:
        conn.close()
    assert query != []
    assert query.count('"') // 2 == 8
    assert any(term in query for term in ('"hotel"', '"indigo"', '"juliett"'))



def test_multi_token_query_keeps_single_eligible_term(brain_home):
    mid = _add(brain_home, "Quasar rule", "quasar retrieval guidance", scope="global")

    rows = semantic.search_memories(brain_home, "quasar unknownword", project_id=None)

    assert [row["memory_id"] for row in rows] == [mid]

def test_literal_stoplist_removes_contraction_fragments():
    assert semantic._query_candidates("what's aren't couldn't alpha bravo") == [
        "alpha",
        "bravo",
    ]

def test_long_prompt_no_longer_returns_empty(brain_home):
    mid = _add(
        brain_home,
        "Rare retrieval rule",
        "quasar nebula retrieval rule",
        scope="global",
    )
    long_prompt = "quasar nebula retrieval rule " + " ".join(f"noise{i}" for i in range(40))

    rows = semantic.search_memories(brain_home, long_prompt)

    assert rows
    assert rows[0]["memory_id"] == mid


def test_query_source_is_objective_when_capsule_present(brain_home, monkeypatch):
    working_set.init_capsule(brain_home, "query-session", "capsule objective")
    working_set.update_capsule(brain_home, "query-session", next_action="capsule next action")
    seen: list[str] = []

    def capture(home, query, **kwargs):
        seen.append(query)
        return []

    monkeypatch.setattr(semantic, "search_memories", capture)
    autoinject.BrainLifecycle(brain_home).prepare_injection(
        "task text must not be used",
        project_id=None,
        session_id="query-session",
    )

    assert seen == ["capsule objective capsule next action"]
