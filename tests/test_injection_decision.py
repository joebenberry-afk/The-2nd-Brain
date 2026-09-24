"""S2 retrieval/decision separation (PERF-01, RET-02, RET-05).

Retrieval now only proposes candidates; a separate deterministic decision answers
whether a candidate *contributes to this request*, using corpus statistics rather
than word lists: a match counts when a term the corpus does not spread broadly is
confirmed by the memory's own headline/title, when two near-unique terms coincide,
or — when the corpus has no discriminating term left — when the headline confirms
the request's terms.

Live-corpus seed case (NB-OK-17): 81 of 116 memories satisfied 2 of the 3 surviving
plan terms ('tools', 'use', 'exactly'), the top one being the OMP workbench doc, so
the packet was injected on a prompt that needed no memory at all. The fixture corpus
below reproduces that mechanism at test scale, plus the counterpart cases that must
still inject (concise/imperative/instruction-heavy migration requests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_brain import autoinject, db, semantic
from second_brain.contracts import BrainInjectionDecision, InjectionDecision, NoInjectionReason

PROJECT = "proj-a"


# ---------------------------------------------------------------------------
# Corpus-statistic decision unit tests (no database).
# ---------------------------------------------------------------------------


def _plan(
    terms: tuple[str, ...],
    frequencies: dict[str, int],
    total: int,
    text: str = "",
    distinct: dict[str, int] | None = None,
):
    return semantic.QueryMatchPlan(
        text=text or " ".join(terms),
        expression="(" + " OR ".join(f'"{t}"*' for t in terms) + ")",
        terms=terms,
        required=2,
        frequencies=frequencies,
        total_documents=total,
        distinct=dict(frequencies) if distinct is None else distinct,
    )


def test_plan_specificity_boundaries() -> None:
    plan = _plan(
        ("tools", "use", "exactly", "one"),
        {"tools": 6, "use": 16, "exactly": 30, "one": 45},
        116,
    )
    # 10% of 116 = 12 documents; the floor of 2 keeps small corpora usable.
    assert plan.is_specific("tools") and not plan.is_specific("use")
    assert plan.has_discriminative_term()
    assert not plan.is_ubiquitous("use") and plan.is_ubiquitous("one") is False
    tiny = _plan(("delegation", "rules"), {"delegation": 3, "rules": 3}, 3)
    assert not tiny.is_specific("delegation")
    assert tiny.is_ubiquitous("delegation") and not tiny.has_discriminative_term()


def test_body_only_overlap_is_not_evidence() -> None:
    """NB-OK-17: instruction terms matched only inside a body must not inject."""
    plan = _plan(("tools", "use", "exactly"), {"tools": 6, "use": 16, "exactly": 30}, 116)
    row = {
        "title": "OMP 18.1.15 documented workbench",
        "_body": "structured readers are tools you may use exactly as documented",
    }
    evidence = semantic.match_evidence(row, plan)
    assert evidence.matched == ("tools", "use", "exactly")
    assert evidence.headline_matched == ()
    assert evidence.contributing is False
    # The same terms confirmed by the memory's own headline are evidence.
    headline_row = {"title": "Documented tools contract", "_body": "use exactly as documented"}
    assert semantic.match_evidence(headline_row, plan).contributing is True


def test_generic_single_term_headline_is_not_evidence() -> None:
    """'Summarize ... in one sentence.' matched a headline word in a third of the corpus."""
    plan = _plan(("one",), {"one": 45}, 116)
    row = {"title": "T1 generalization protocol correction: is not one archetype", "_body": ""}
    evidence = semantic.match_evidence(row, plan)
    assert evidence.headline_matched == ("one",)
    assert evidence.contributing is False


def test_quoted_headline_mention_needs_a_quoted_request() -> None:
    """A memory *about* the string 'format' is not evidence for a formatting instruction."""
    plan = _plan(("format",), {"format": 1}, 116, text="Format the answer as a table.")
    row = {"title": "Skill security detector flags 'format' anywhere", "_body": ""}
    assert semantic.match_evidence(row, plan).contributing is False
    quoted = _plan(("format",), {"format": 1}, 116, text="Why does it flag the word 'format'?")
    assert semantic.match_evidence(row, quoted).contributing is True


def test_term_breadth_counts_prefix_matches_not_exact_tokens(brain_home) -> None:
    """A short term rare by token can be broad by prefix ('mem' also matches 'memory')."""
    _add(brain_home, "Native memory settings", "memory.md and memory buckets per project")
    _add(brain_home, "Memory id lookup", "ids look like mem-xxxxxxxxxxxx in packets")
    _add(brain_home, "Memory packet budget", "memory packets are capped per turn")
    for index in range(5):
        _add(brain_home, f"Shell note {index}", f"shell command {index} runs in the venv")
    plan = semantic.query_match_plan(brain_home, "Tell me about mem-ffffffffffff.")
    assert plan.terms == ("mem",)
    assert plan.frequencies["mem"] == 1
    # Prefix matching ("mem"* also matches "memory"/"mem-...") is the measured
    # breadth, an upper bound (a document holding two matching tokens counts twice).
    assert plan.document_frequency("mem") >= 3
    assert plan.is_specific("mem") is False
    assert plan.is_ubiquitous("mem") is False
    assert plan.has_discriminative_term() is False
    assert semantic.match_evidence(
        {"title": "Memory id lookup", "_body": "ids look like mem-xxxxxxxxxxxx"}, plan
    ).contributing is False


def test_unique_coincidence_needs_two_terms() -> None:
    plan = _plan(
        ("leaving", "wal", "restore"),
        {"leaving": 2, "wal": 1, "restore": 3},
        116,
    )
    one = {"title": "SQLite safety", "_body": "leaving the wal file behind"}
    assert semantic.match_evidence(one, plan).unique_matched == ("leaving", "wal")
    assert semantic.match_evidence(one, plan).contributing is True
    single = {"title": "SQLite safety", "_body": "leaving the file behind"}
    assert semantic.match_evidence(single, plan).unique_matched == ("leaving",)
    assert semantic.match_evidence(single, plan).contributing is False


def test_ubiquitous_plan_falls_back_to_headline_confirmation() -> None:
    plan = _plan(("delegation", "rules"), {"delegation": 3, "rules": 3}, 3)
    row = {"title": "Delegation rules", "_body": "delegation rules for everyone"}
    assert semantic.match_evidence(row, plan).contributing is True


def test_single_matched_term_needs_rarity_or_full_request_coverage() -> None:
    """VG-N06: one mid-frequency headline word is not evidence for a wider request.

    'In one sentence, what is a Python dict? Reply with one sentence.' reached the
    PYTHONHOME memory on 'python' alone (df 9 of 116) while 'dict' and 'sentence'
    are not in the corpus at all, so the row explains neither of them either.
    """
    plan = _plan(
        ("python", "one"),
        {"python": 9, "one": 45},
        116,
        text="In one sentence, what is a Python dict? Reply with one sentence.",
    )
    row = {
        "title": "Brain machine: PYTHONHOME pollution breaks bare python launches",
        "_body": "shims strip PYTHONHOME before launching python",
    }
    evidence = semantic.match_evidence(row, plan)
    # The request's content terms are the request's own tokens, not the plan's
    # vocabulary-filtered subset: 'dict' and 'sentence' are not in the corpus.
    assert plan.content_terms() == ("one", "sentence", "python", "dict", "reply")
    assert evidence.matched == ("python",)
    assert evidence.headline_matched == ("python",)
    assert evidence.unexplained_terms == ("one", "sentence", "dict", "reply")
    assert evidence.contributing is False

    # A row that explains every other content term needs no rare term: the request
    # asked for this row's own subject and nothing else.
    covered = _plan(("python",), {"python": 9}, 116, text="python launches")
    covered_evidence = semantic.match_evidence(row, covered)
    assert covered_evidence.unexplained_terms == ()
    assert covered_evidence.contributing is True

    # A near-unique matched term names one memory's own subject matter: still evidence.
    rare = _plan(("pythonhome",), {"pythonhome": 1}, 116, text="How do I clear PYTHONHOME?")
    rare_evidence = semantic.match_evidence(row, rare)
    assert rare_evidence.unexplained_terms == ("clear",)
    assert rare_evidence.contributing is True


def test_two_matched_terms_keep_the_weaker_headline_evidence() -> None:
    """The single-term guard judges single-term rows only; a second match is enough."""
    plan = _plan(
        ("python", "launch"),
        {"python": 9, "launch": 4},
        116,
        text="In one sentence, what is a Python launcher? Reply with one sentence.",
    )
    row = {
        "title": "Python launcher hygiene",
        "_body": "shims strip malformed variables before launching anything",
    }
    evidence = semantic.match_evidence(row, plan)
    assert evidence.matched == ("python", "launch")
    assert evidence.unexplained_terms == ()
    assert evidence.contributing is True


def test_plan_without_terms_passes_rows_through() -> None:
    plan = semantic.QueryMatchPlan(text="!!")
    rows = [{"title": "x", "_body": "y"}]
    assert semantic.contribution_filter(rows, plan) == rows


# ---------------------------------------------------------------------------
# Pipeline fixtures.
# ---------------------------------------------------------------------------


def _add(home: Path, title: str, body: str, *, project_id: str = PROJECT) -> str:
    memory_id = semantic.add_memory(
        home, title, body, scope="project", project_id=project_id, grade="TESTED"
    )
    semantic.curate(home, memory_id, status="current")
    return memory_id


def _inject(home: Path, task: str, **kw) -> BrainInjectionDecision:
    return autoinject.BrainLifecycle(home).prepare_injection(
        task,
        project_id=kw.pop("project_id", PROJECT),
        agent_id="a1",
        role_profile=kw.pop("role_profile", "worker"),
        session_id=kw.pop("session_id", "s1"),
        branch_id=kw.pop("branch_id", "main"),
    )


def _overlap_corpus(home: Path) -> dict[str, str]:
    """Corpus where instruction vocabulary is spread across bodies, as in the live one."""
    return {
        "workbench": _add(
            home,
            "OMP 18.1.15 documented workbench",
            "structured file and archive readers are tools you may use exactly as documented",
        ),
        "config": _add(
            home,
            "OMP 18.1.15 documented configuration",
            "profiles and settings: use exactly one profile per project",
        ),
        "sessions": _add(
            home,
            "OMP 18.1.15 documented sessions",
            "conversation trees resume; tools and use exactly one tree",
        ),
        "hub": _add(home, "Hub status", "the hub reports tools status per job"),
        "migration": _add(home, "Migration ordering", "apply migrations in numeric order"),
        "shell": _add(home, "Shell commands", "shell commands run inside the venv"),
        "packets": _add(home, "Packet items", "a packet contains ranked items"),
    }


def _single_term_corpus(home: Path) -> dict[str, str]:
    """VG-N06 at fixture scale: one matched term that is specific but not near-unique.

    The request's vocabulary has to sort into exactly what the live case had: 30
    memories ('python' then names 3 of them, the specificity bar at 10%), one row
    with 'python' in its headline and two with it only in the body, and a rare
    identifier ('lantern', one memory) for the other direction.
    """
    corpus = {
        "launcher": _add(
            home,
            "Python launcher hygiene",
            "shims strip malformed environment variables before launching python",
        ),
        "venv": _add(home, "Venv layout", "the venv holds a python interpreter copy"),
        "pin": _add(home, "Version pin", "the pinned python version is recorded"),
        "lantern": _add(home, "Lantern cache identifier", "the Lantern cache id is lantern-7719"),
    }
    for index in range(26):
        _add(home, f"Unrelated note {index}", f"filler text {index}")
    return corpus


def _attempt_records(home: Path) -> list[dict]:
    """brain_retrieval_attempt records for this brain's telemetry dir."""
    directory = home / "telemetry" / "agent-performance"
    if not directory.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("kind") == "brain_retrieval_attempt":
                records.append(record)
    return records


def test_instruction_overlap_prompt_does_not_inject(brain_home) -> None:
    """NB-OK-17 shape: candidates are found, none of them contributes -> no packet."""
    corpus = _overlap_corpus(brain_home)
    decision = _inject(
        brain_home, "Reply with exactly: NB-OK-17. Do not use any tools.", session_id="s-nb"
    )
    assert decision.decision is InjectionDecision.NO_INJECTION
    # The abstention is the relevance decision, not an empty search result.
    assert decision.reason is NoInjectionReason.LOW_CONFIDENCE
    assert decision.candidate_ids, "expected retrieved candidates that were dropped"
    assert decision.selected_ids == []
    assert corpus["workbench"] in decision.candidate_ids
    attempt = [
        r
        for r in _attempt_records(brain_home)
        if r.get("kind") == "brain_retrieval_attempt" and r.get("session") == "s-nb"
    ][-1]
    assert attempt["candidate_count"] >= 1
    assert attempt["contributing_count"] == 0
    assert attempt["noncontributing_count"] >= 1


def test_single_term_guard_abstains_on_a_generic_question_and_keeps_a_rare_one(
    brain_home,
) -> None:
    """Both directions end to end: the generic question drops, the rare-term one stays."""
    corpus = _single_term_corpus(brain_home)
    generic = _inject(
        brain_home,
        "In one sentence, what is a Python dict? Reply with one sentence.",
        session_id="s-single-generic",
    )
    assert generic.decision is InjectionDecision.NO_INJECTION
    # Candidates were retrieved and judged: the abstention is the contribution rule.
    assert generic.reason is NoInjectionReason.LOW_CONFIDENCE
    assert corpus["launcher"] in generic.candidate_ids
    attempt = [
        r
        for r in _attempt_records(brain_home)
        if r.get("kind") == "brain_retrieval_attempt" and r.get("session") == "s-single-generic"
    ][-1]
    assert attempt["candidate_count"] >= 1 and attempt["contributing_count"] == 0

    rare = _inject(brain_home, "Remind me of the lantern id.", session_id="s-single-rare")
    assert rare.decision is InjectionDecision.INJECT
    assert rare.selected_ids == [corpus["lantern"]]


def test_contribution_abstention_is_recorded_as_a_decision(brain_home) -> None:
    _overlap_corpus(brain_home)
    _inject(brain_home, "Reply with exactly: NB-OK-17. Do not use any tools.", session_id="s-rec")
    conn = db.connect(db.db_path(brain_home), readonly=True)
    try:
        rows = conn.execute(
            "SELECT inputs_json, kind FROM decisions WHERE session_id = ?", ("s-rec",)
        ).fetchall()
    finally:
        conn.close()
    assert rows and rows[0]["kind"] == "retrieval"
    assert json.loads(rows[0]["inputs_json"])["gate"] == "contribution"


@pytest.mark.parametrize(
    "task",
    [
        "In what order should database migrations be applied?",
        "Apply the database migrations in the right order for schema 28.",
        (
            "Answer from your current context only; do not read files or run shell commands. "
            "Question: in what order should the database migrations be applied? "
            "Finish with exactly one line."
        ),
        "Without reading any files, tell me what the migration ordering rule is.",
    ],
)
def test_migration_requests_still_inject(brain_home, task: str) -> None:
    corpus = _overlap_corpus(brain_home)
    decision = _inject(brain_home, task, session_id=f"s-mig-{abs(hash(task)) % 1000}")
    assert decision.decision is InjectionDecision.INJECT
    assert corpus["migration"] in decision.selected_ids
    assert corpus["workbench"] not in decision.selected_ids


def test_long_prompt_with_irrelevant_hit_recovers_memory(brain_home) -> None:
    """The S1 counter-example: the full query matches boilerplate, the request still wins."""
    corpus = _overlap_corpus(brain_home)
    decision = _inject(
        brain_home,
        "Do not use any tools and do not read files; answer from memory only, keep it to "
        "one line, no markdown. Tell me in what order the database migrations should be "
        "applied.",
        session_id="s-long",
    )
    assert decision.decision is InjectionDecision.INJECT
    assert decision.selected_ids == [corpus["migration"]]


def test_narrowed_retry_recovers_request_diluted_by_filler(brain_home) -> None:
    """A long request whose filler terms dilute the match requirement still recovers."""
    target = _add(brain_home, "Migration ordering", "apply migrations in order")
    for index, filler in enumerate(("one", "two", "three"), start=1):
        _add(
            brain_home,
            f"Shell notes {filler}",
            f"the shell helper runs the shell helper again for pass {index}",
        )
    decision = _inject(
        brain_home,
        "Without reading notes or running the shell helper, tell me the migration "
        "ordering rule.",
        session_id="s-narrow",
    )
    assert decision.decision is InjectionDecision.INJECT
    assert decision.selected_ids == [target]
    modes = [
        r.get("query_mode")
        for r in _attempt_records(brain_home)
        if r.get("kind") == "brain_retrieval_attempt" and r.get("session") == "s-narrow"
    ]
    assert modes and modes[-1] == "idf_narrowed"


def test_explicit_query_keeps_body_only_match(brain_home) -> None:
    """An explicit user query is not an automatic injection: it keeps body-only matches."""
    target = _add(brain_home, "Long body fact", "longbody " + "x" * 300)
    question = "longbody"
    automatic = autoinject.prepare_injection(
        brain_home,
        autoinject.RetrievalIntent(
            task_text=question,
            project_id=PROJECT,
            agent_id="driver",
            role_profile="worker",
            session_id="s-auto-body",
        ),
    )
    assert automatic.decision is InjectionDecision.NO_INJECTION
    explicit = autoinject.prepare_injection(
        brain_home,
        autoinject.RetrievalIntent(
            task_text=question,
            project_id=PROJECT,
            agent_id="brainctl",
            role_profile="cli",
            session_id="s-explicit-body",
            explicit=True,
        ),
        retrieval_text=question,
    )
    assert explicit.decision is InjectionDecision.INJECT
    assert explicit.selected_ids == [target]
    # The validity gates still apply to an explicit query.
    other = autoinject.prepare_injection(
        brain_home,
        autoinject.RetrievalIntent(
            task_text=question,
            project_id="proj-b",
            agent_id="brainctl",
            role_profile="cli",
            session_id="s-explicit-wrong-project",
            explicit=True,
        ),
        retrieval_text=question,
    )
    assert other.decision is InjectionDecision.NO_INJECTION
    assert other.reason is NoInjectionReason.WRONG_PROJECT


def test_young_corpus_automatic_injection_uses_headline_confirmation(brain_home) -> None:
    """A two-memory corpus has no rare term left; headline confirmation still injects."""
    target = _add(brain_home, "Delegation rules", "delegation rules for everyone")
    _add(brain_home, "Delegation rules draft", "delegation rules draft for everyone")
    decision = _inject(brain_home, "delegation rules", session_id="s-young")
    assert decision.decision is InjectionDecision.INJECT
    assert target in decision.selected_ids


def test_query_with_path_and_symbol_terms_still_injects(brain_home) -> None:
    """RET-02: paths/symbols in a request must reach the memory that answers it."""
    target = _add(
        brain_home,
        "Backup restore leaves -wal files behind",
        "restore keeps a -wal and -shm beside the restored database until checkpoint",
    )
    _add(brain_home, "Packet items", "a packet contains ranked items")
    _add(brain_home, "Shell commands", "shell commands run inside the venv")
    decision = _inject(
        brain_home,
        "Why does src/second_brain/backup.py leave a -wal file after a restore?",
        session_id="s-symbol",
    )
    assert decision.decision is InjectionDecision.INJECT
    assert target in decision.selected_ids


def test_archived_and_wrong_project_memories_not_injected(brain_home) -> None:
    live = _add(brain_home, "Migration ordering", "apply migrations in numeric order")
    archived = _add(brain_home, "Migration ordering (old)", "apply migrations in numeric order")
    other_project = _add(
        brain_home, "Migration ordering there", "apply migrations in numeric order",
        project_id="proj-b",
    )
    semantic.curate(brain_home, archived, status="archived")

    decision = _inject(brain_home, "In what order should database migrations be applied?")
    assert decision.decision is InjectionDecision.INJECT
    assert decision.selected_ids == [live]
    assert archived not in decision.selected_ids
    assert other_project not in decision.selected_ids

    wrong = _inject(
        brain_home,
        "In what order should database migrations be applied?",
        project_id="proj-b",
        session_id="s-wrong",
    )
    assert wrong.decision is InjectionDecision.INJECT
    assert wrong.selected_ids == [other_project]


def test_focused_query_keeps_indirect_questions() -> None:
    prompt = (
        "Do not read files. "
        "Tell me in what order the database migrations should be applied."
    )
    assert (
        autoinject._focused_query_text(prompt, "second-brain")
        == "Tell me in what order the database migrations should be applied."
    )
    assert autoinject._focused_query_text("Rename tmp to buffer.", "second-brain") is None


def test_exact_ref_match_counts_as_contribution_evidence(brain_home) -> None:
    """A named memory id is evidence by construction; admission gates still apply."""
    target = _add(brain_home, "Long body fact", "longbody " + "x" * 300)
    by_id = _inject(brain_home, target, session_id="s-ref-id")
    assert by_id.decision is InjectionDecision.INJECT
    assert by_id.selected_ids == [target]

    # Bare hex (no mem- prefix) resolves to the same identity.
    bare = target.removeprefix("mem-")
    by_hex = _inject(brain_home, bare, session_id="s-ref-hex")
    assert by_hex.decision is InjectionDecision.INJECT
    assert by_hex.selected_ids == [target]

    # Status and project admission still decide, even for an exact reference.
    archived = _add(brain_home, "Archived fact", "archived body text")
    semantic.curate(brain_home, archived, status="archived")
    blocked = _inject(brain_home, archived, session_id="s-ref-archived")
    assert blocked.decision is InjectionDecision.NO_INJECTION
    other_project = _add(
        brain_home, "Other project fact", "other project body", project_id="proj-b"
    )
    wrong = _inject(brain_home, other_project, project_id=PROJECT, session_id="s-ref-project")
    assert wrong.decision is InjectionDecision.NO_INJECTION
    assert wrong.reason is NoInjectionReason.WRONG_PROJECT


def test_contribution_decision_sees_bodies_dropped_for_broad_result_sets(
    brain_home, monkeypatch
) -> None:
    """`_search_fts` strips `_body` above its scan limit; the decision must still see it."""
    target = _add(brain_home, "Retry helper contract", "quasar nebula calibration values")
    for index in range(4):
        _add(brain_home, f"Shell note {index}", f"shell command {index} runs in the venv")
    # Force the index to drop bodies for every result set, as it does above its limit.
    monkeypatch.setattr(semantic, "_DEDUPE_BODY_SCAN_LIMIT", 0)
    decision = _inject(brain_home, "quasar nebula", session_id="s-hydrated")
    assert decision.decision is InjectionDecision.INJECT
    assert decision.selected_ids == [target]


def test_prefix_breadth_counts_documents_over_the_prefix(brain_home, monkeypatch) -> None:
    """Breadth is measured over the prefix; ubiquity needs the exact distinct count."""
    monkeypatch.setattr(semantic, "_DEDUPE_BODY_SCAN_LIMIT", 0)
    _add(brain_home, "Alpha pair", "alpha alphabet tokens in one memory")
    _add(brain_home, "Alpha single", "alpha only here")
    _add(brain_home, "Alphabet single", "alphabet only here")
    for index in range(3):
        _add(brain_home, f"Unrelated {index}", f"nothing relevant in memory {index}")
    plan = semantic.query_match_plan(brain_home, "alpha alphabet")
    # Two exact tokens match the "alpha" prefix: alpha in two memories, alphabet in two.
    assert plan.frequencies["alpha"] == 2 and plan.frequencies["alphabet"] == 2
    # The vocabulary range sum is an upper bound (the memory holding both tokens counts
    # once per token) and is what rarity claims use; when the bound crosses the ubiquity
    # threshold it is replaced by the tighter exact count.
    assert plan.distinct["alpha"] == 3
    assert plan.breadth["alpha"] == 3
    assert plan.is_specific("alpha") is False  # 3 > max(2, ceil(0.10 * 6))
    assert plan.is_ubiquitous("alpha") is False  # 3 of 6 documents is not more than half
    # A term with no measured distinct count is never treated as ubiquitous.
    assert "unrelat" not in plan.distinct and plan.is_ubiquitous("unrelat") is False
