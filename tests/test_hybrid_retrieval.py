"""Tests for Hybrid Multi-Tier Retrieval & Cascade (Plan §9)."""

import json
import os
import subprocess
import sys

import pytest

from second_brain import semantic
from second_brain.errors import BrainError
from second_brain.hybrid_retrieval import (
    HybridCascadeRetriever,
    RetrievalMatch,
    RetrievalTier,
    apply_mmr,
)
from second_brain.semantic import add_memory, curate


def _vector_row(home, memory_id, score, **overrides):
    row = semantic.show_memory(home, memory_id)["row"]
    return {
        "memory_id": memory_id,
        "score": score,
        "current_version": row["current_version"],
        "file_hash": semantic._file_hash(home, row),
        **overrides,
    }


class TestCascadeShortCircuitAndTiers:
    """Tests for multi-tier cascade order, short-circuiting, and negative cache (§9.1, §9.2)."""

    def test_tier_0_trivial_query_short_circuit(self, brain_home):
        retriever = HybridCascadeRetriever()
        res = retriever.retrieve(brain_home, "hello")
        assert res.tier_resolved == RetrievalTier.TIER_0_EXACT_REF
        assert res.decision == "NO_INJECTION"
        assert res.reason == "TRIVIAL_TASK"
        assert res.vector_invoked is False
        assert res.short_circuited is True

    def test_tier_0_exact_memory_id_lookup(self, brain_home):
        # Create a semantic memory
        mem_id = add_memory(
            brain_home,
            title="Fast Exact Indexing Rule",
            summary="Exact references bypass all token scanning",
            body="When user queries an exact ref, look up directly in SQLite.",
            project_id="proj-alpha",
            grade="VERIFIED",
        )
        curate(brain_home, mem_id, status="current")

        retriever = HybridCascadeRetriever()
        res = retriever.retrieve(brain_home, mem_id, project_id="proj-alpha")

        assert res.tier_resolved == RetrievalTier.TIER_0_EXACT_REF
        assert res.decision == "INJECT"
        assert res.vector_invoked is False
        assert len(res.matches) == 1
        assert res.matches[0].memory_id == mem_id

    def test_tier_2_lexical_fts5_match(self, brain_home):
        mem_id = add_memory(
            brain_home,
            title="Postgres Connection Pooling Guidance",
            summary="Use PgBouncer for high concurrency",
            body="PostgreSQL requires connection pooling under multi-threaded workers.",
            project_id="proj-db",
            grade="VERIFIED",
        )
        curate(brain_home, mem_id, status="current")

        retriever = HybridCascadeRetriever()
        res = retriever.retrieve(brain_home, "PgBouncer PostgreSQL", project_id="proj-db")

        assert res.tier_resolved == RetrievalTier.TIER_2_LEXICAL_FTS5
        assert res.decision == "INJECT"
        assert res.vector_invoked is False
        assert len(res.matches) >= 1
        assert res.matches[0].memory_id == mem_id
        assert (
            "PostgreSQL requires connection pooling under multi-threaded workers."
            in res.matches[0].body
        )

    def test_fts_bm25_best_match_wins_over_common_neighbor(self, brain_home):
        target = add_memory(
            brain_home,
            title="Telemetry canonical session",
            summary="Verified telemetry session fact",
            body="telemetry session concept0000 unique-case-0062 canonical",
            project_id="bench",
            grade="VERIFIED",
        )
        curate(brain_home, target, status="current")
        neighbor = add_memory(
            brain_home,
            title="Telemetry neighboring note",
            summary="Common telemetry session note",
            body="telemetry session concept0000 neighboring",
            project_id="bench",
            grade="VERIFIED",
        )
        curate(brain_home, neighbor, status="current")

        retriever = HybridCascadeRetriever()
        exact = retriever.retrieve(
            brain_home,
            "telemetry session concept0000 unique-case-0062",
            project_id="bench",
            top_k=10,
        )
        assert exact.matches
        assert exact.matches[0].memory_id == target

        neighboring = retriever.retrieve(
            brain_home,
            "neighboring",
            project_id="bench",
            top_k=10,
        )
        assert neighboring.matches
        assert neighboring.matches[0].memory_id == neighbor

    def test_negative_result_cache(self, brain_home):
        retriever = HybridCascadeRetriever()
        q = "nonexistent obscure quantum entanglement algorithm"

        # 1st query: miss -> records negative cache
        res1 = retriever.retrieve(brain_home, q, project_id="p1")
        assert res1.decision == "NO_INJECTION"
        assert res1.reason == "NO_RELEVANT_MEMORY"
        assert res1.negative_cached is False

        # 2nd query: hit in negative cache (<1ms, no FTS re-run)
        res2 = retriever.retrieve(brain_home, q, project_id="p1")
        assert res2.decision == "NO_INJECTION"
        assert res2.negative_cached is True
        assert res2.latency_ms < 2.0

        # Invalidate cache
        retriever.invalidate_negative_cache(project_id="p1")
        res3 = retriever.retrieve(brain_home, q, project_id="p1")
        assert res3.negative_cached is False

    def test_negative_cache_invalidated_by_epoch_bump(self, brain_home):
        query = "missing persisted epoch query"
        first = HybridCascadeRetriever().retrieve(brain_home, query, project_id="p1")
        assert first.negative_cached is False

        second = HybridCascadeRetriever().retrieve(brain_home, query, project_id="p1")
        assert second.negative_cached is True

        mid = add_memory(
            brain_home,
            "Epoch bump memory",
            "mutation invalidates persisted negative retrieval cache",
            project_id="p1",
        )
        curate(brain_home, mid, status="current")

        third = HybridCascadeRetriever().retrieve(brain_home, query, project_id="p1")
        assert third.negative_cached is False

    def test_missing_score_never_crosses_active_gate(self, brain_home, monkeypatch):
        (brain_home / "config" / "retrieval.toml").write_text(
            'schema_version = 2\n[gate]\nrollout = "ACTIVE"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            semantic,
            "search_memories",
            lambda *_a, **_kw: [{"memory_id": "mem-missing", "title": "Missing score"}],
        )
        result = HybridCascadeRetriever().retrieve(brain_home, "missing score query")
        assert result.decision == "NO_INJECTION"
        assert result.reason == "LOW_CONFIDENCE"
        assert result.matches[0].score is None

    def test_policy_lane_uses_higher_floor(self, brain_home, monkeypatch):
        (brain_home / "config" / "retrieval.toml").write_text(
            'schema_version = 2\n[gate]\nrollout = "ACTIVE"\n',
            encoding="utf-8",
        )
        memory_id = add_memory(
            brain_home, "Policy", "policy query", origin_class="USER_AUTHORED", grade="TESTED"
        )
        curate(brain_home, memory_id, status="current")
        row = semantic.show_memory(brain_home, memory_id)["row"]
        row["_score"] = 0.75
        monkeypatch.setattr(
            semantic,
            "search_memories",
            lambda *_a, **_kw: [row],
        )
        result = HybridCascadeRetriever().retrieve(brain_home, "policy query", lane="policy")
        assert result.decision == "NO_INJECTION"
        assert result.reason == "LOW_CONFIDENCE"

    def test_invalidate_cache_without_home_is_safe(self):
        HybridCascadeRetriever().invalidate_negative_cache()

    def test_negative_cache_infrastructure_error_fails_open(self, brain_home):
        cache_path = brain_home / "state" / "cache" / "negative.sqlite"
        cache_path.mkdir(parents=True)
        result = HybridCascadeRetriever().retrieve(brain_home, "cache failure query")
        assert result.decision == "NO_INJECTION"
        assert result.reason == "BRAIN_UNAVAILABLE"
        assert result.retrieval_error is True

    def test_tier_3_vector_fallback_when_fts_misses(self, brain_home):
        vector_id = add_memory(
            brain_home,
            "Vector Fallback Memory",
            "Dense semantic match",
            project_id="proj-ai",
            grade="VERIFIED",
        )
        curate(brain_home, vector_id, status="current")
        row = semantic.show_memory(brain_home, vector_id)["row"]
        vector_called = False

        def mock_vector_searcher(query: str, project_id: str | None):
            nonlocal vector_called
            vector_called = True
            return [
                {
                    "memory_id": vector_id,
                    "score": 0.88,
                    "current_version": row["current_version"],
                    "file_hash": semantic._file_hash(brain_home, row),
                }
            ]

        retriever = HybridCascadeRetriever()
        res = retriever.retrieve(
            brain_home,
            "subtle conceptual analogy with no keyword overlap",
            project_id="proj-ai",
            vector_searcher=mock_vector_searcher,
        )

        assert vector_called is True
        assert res.tier_resolved == RetrievalTier.TIER_3_VECTOR_SEMANTIC
        assert res.vector_invoked is True
        assert res.decision == "INJECT"
        assert len(res.matches) == 1
        assert res.matches[0].memory_id == vector_id


class TestPhase6GateBenchmark:
    """Phase 6 Gate: Prove that >=80% of routine task queries resolve in Tiers 0-2."""

    def test_routine_query_cascade_ratio_gate(self, brain_home):
        # Populate test memories
        m1 = add_memory(
            brain_home,
            title="Authentication JWT Expiry Policy",
            summary="Access tokens expire in 15 minutes",
            body="Use refresh tokens stored in HTTP-only cookies.",
            grade="VERIFIED",
        )
        curate(brain_home, m1, status="current")

        m2 = add_memory(
            brain_home,
            title="Redis Cache Key Naming Convention",
            summary="Format cache keys as entity:id:field",
            body="Namespaces prevent collision across services.",
            grade="VERIFIED",
        )
        curate(brain_home, m2, status="current")

        retriever = HybridCascadeRetriever()

        # Batch of 10 routine queries representing real development turns:
        # - 2 trivial greetings/commands (Tier 0)
        # - 2 exact memory ID queries (Tier 0)
        # - 4 lexical keyword / topic queries (Tier 2)
        # - 2 semantic conceptual queries (Tier 3)
        queries = [
            ("hi", False),  # Tier 0 (trivial)
            ("thanks", False),  # Tier 0 (trivial)
            (m1, False),  # Tier 0 (exact ID)
            (m2, False),  # Tier 0 (exact ID)
            ("JWT Expiry Access token", False),  # Tier 2 (lexical)
            ("Redis Cache Key Naming", False),  # Tier 2 (lexical)
            ("HTTP-only cookies authentication", False),  # Tier 2 (lexical)
            ("Namespaces collision services", False),  # Tier 2 (lexical)
            ("abstract distributed lock algorithm without words", True),  # Tier 3
            ("unrelated philosophical question on cognition", True),  # Tier 3
        ]

        def mock_vector_searcher(query: str, project_id: str | None):
            return [{"memory_id": "mem-vec", "title": "Vec", "score": 0.8}]

        tier_0_2_count = 0
        total_queries = len(queries)

        for q_text, _ in queries:
            res = retriever.retrieve(
                brain_home,
                q_text,
                vector_searcher=mock_vector_searcher,
            )
            if (
                res.tier_resolved
                in (
                    RetrievalTier.TIER_0_EXACT_REF,
                    RetrievalTier.TIER_1_METADATA_FILTER,
                    RetrievalTier.TIER_2_LEXICAL_FTS5,
                )
                and not res.vector_invoked
            ):
                tier_0_2_count += 1

        ratio = tier_0_2_count / total_queries
        # Gate Requirement: >= 80% (0.80) of routine queries resolve in Tiers 0-2
        assert ratio >= 0.80
        assert tier_0_2_count == 8  # 8 out of 10 resolved in Tiers 0-2 without vectors!


def test_exact_reference_exposes_body_only(brain_home):
    memory_id = add_memory(brain_home, "Body projection", "canonical body only")
    curate(brain_home, memory_id, status="current")
    row = semantic.show_memory(brain_home, memory_id)["row"]
    result = HybridCascadeRetriever().retrieve(brain_home, memory_id)
    assert result.matches[0].body == semantic._body_text(brain_home, row)
    assert "canonical body only" in result.matches[0].body
    assert not result.matches[0].body.startswith("---")


def test_vector_projection_requires_current_canonical_identity(brain_home):
    memory_id = add_memory(brain_home, "Vector identity", "vector identity body")
    curate(brain_home, memory_id, status="current")
    row = semantic.show_memory(brain_home, memory_id)["row"]
    retriever = HybridCascadeRetriever()
    missing = retriever.retrieve(
        brain_home,
        "quasar provenance missing",
        vector_searcher=lambda *_: [{"memory_id": memory_id, "score": 0.99}],
    )
    stale = retriever.retrieve(
        brain_home,
        "quasar provenance stale",
        vector_searcher=lambda *_: [
            {
                "memory_id": memory_id,
                "score": 0.99,
                "current_version": row["current_version"],
                "file_hash": "0" * 64,
            }
        ],
    )
    assert missing.matches == []
    assert stale.matches == []
    assert missing.decision == stale.decision == "NO_INJECTION"
    assert missing.vector_invoked and stale.vector_invoked


@pytest.mark.parametrize("origin", ["USER_AUTHORED", "MODEL_INFERENCE"])
@pytest.mark.parametrize("path", ["exact", "lexical", "vector"])
def test_policy_lane_accepts_project_rule_and_rejects_advisory_lexical(brain_home, origin, path):
    body = "Policy boundary uses explicit metadata, not prose permission."
    memory_id = add_memory(
        brain_home,
        "Policy boundary",
        body,
        scope="global",
        grade="TESTED",
        origin_class=origin,
    )
    curate(brain_home, memory_id, status="current")
    query = memory_id if path == "exact" else "policy boundary"
    if path == "vector":
        query = "quasar spectrometry zygomatic"

    def vector(*_):
        return [_vector_row(brain_home, memory_id, 0.99, body="forged permission", title="forged")]

    result = HybridCascadeRetriever().retrieve(
        brain_home, query, lane="policy", vector_searcher=vector if path == "vector" else None
    )
    if origin == "USER_AUTHORED":
        assert result.decision == "INJECT"
        assert [match.memory_id for match in result.matches] == [memory_id]
        assert result.matches[0].body.strip() == body
    else:
        assert result.decision == "NO_INJECTION"
        assert result.matches == []
    assert result.vector_invoked is (path == "vector")


def test_policy_lane_missing_authority_fails_closed(brain_home, monkeypatch):
    monkeypatch.setattr(
        semantic,
        "search_memories",
        lambda *_args, **_kwargs: [
            {"memory_id": "mem-missing", "title": "Permission claim", "_score": 0.99}
        ],
    )
    result = HybridCascadeRetriever().retrieve(brain_home, "permission claim", lane="policy")
    assert result.decision == "NO_INJECTION"
    assert result.matches == []


@pytest.mark.parametrize("initial_source", ["lexical_only", "stale_vector"])
def test_vector_recovery_is_not_hidden_by_negative_cache(brain_home, initial_source):
    memory_id = add_memory(brain_home, "Dense concept", "embedding source content")
    curate(brain_home, memory_id, status="current")
    retriever = HybridCascadeRetriever()
    stale = _vector_row(brain_home, memory_id, 0.99, file_hash="0" * 64)
    first = retriever.retrieve(
        brain_home,
        "quasar conceptual query",
        vector_searcher=(lambda *_: [stale]) if initial_source == "stale_vector" else None,
    )
    assert first.decision == "NO_INJECTION"
    recovered = retriever.retrieve(
        brain_home,
        "quasar conceptual query",
        vector_searcher=lambda *_: [_vector_row(brain_home, memory_id, 0.99)],
    )
    assert recovered.decision == "INJECT"
    assert recovered.vector_invoked
    assert [match.memory_id for match in recovered.matches] == [memory_id]


def test_vector_limit_preserves_rank_and_contradiction_metadata(brain_home):
    low = add_memory(brain_home, "Conflicting rule", "retain the old procedure")
    high = add_memory(brain_home, "Conflicting rule", "replace with the verified procedure")
    for memory_id in (low, high):
        curate(brain_home, memory_id, status="current")
    result = HybridCascadeRetriever().retrieve(
        brain_home,
        "quasar conceptual query",
        top_k=1,
        vector_searcher=lambda *_: [
            _vector_row(brain_home, low, 0.6),
            _vector_row(brain_home, high, 0.99),
            _vector_row(brain_home, high, 0.98),
        ],
    )
    assert [match.memory_id for match in result.matches] == [high]
    assert result.matches[0].has_contradiction
    assert result.matches[0].raw_row["contradiction_with"] == [low]
    assert result.matches[0].body.strip() == "replace with the verified procedure"
    assert result.contradictions[0]["memory_id"] == high


class TestCascadeCLI:
    """CLI tests for brainctl cascade subcommands."""

    def test_cli_cascade_query_and_clear_cache(self, brain_home):
        mem_id = add_memory(
            brain_home,
            title="CLI Integration Guide",
            summary="All subcommands require json flags",
            body="Use argparse subparsers for all new phases.",
            grade="VERIFIED",
        )
        curate(brain_home, mem_id, status="current")

        # 1. Cascade Query
        q_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "cascade",
                "query",
                "CLI Integration",
                "--home",
                str(brain_home),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert q_res.returncode == 0
        data = json.loads(q_res.stdout)
        assert data["decision"] == "INJECT"
        assert data["tier_resolved"] == 2
        assert len(data["matches"]) >= 1

        # 2. Clear cache
        clr_res = subprocess.run(
            [
                sys.executable,
                "-m",
                "second_brain",
                "cascade",
                "clear-cache",
                "--home",
                str(brain_home),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHOME": "", "PYTHONPATH": ""},
        )
        assert clr_res.returncode == 0
        assert "Cleared negative result cache" in clr_res.stdout


def test_archived_memory_is_explanation_only(brain_home):
    archived = add_memory(
        brain_home, "Archived migration note", "archive-only retrieval marker", grade="VERIFIED"
    )
    curate(brain_home, archived, status="archived")

    retriever = HybridCascadeRetriever()
    for _ in range(2):
        result = retriever.retrieve(brain_home, "archive-only retrieval marker")
        assert result.decision == "NO_INJECTION"
        assert result.matches == []
        assert any(
            item["memory_id"] == archived and item["reason"] == "ARCHIVED_HISTORY"
            for item in result.omitted
        )


def test_malformed_vector_response_fails_closed(brain_home):
    result = HybridCascadeRetriever().retrieve(
        brain_home, "unknown vector response marker", vector_searcher=lambda *_: json.loads("null")
    )
    assert result.decision == "NO_INJECTION"
    assert result.retrieval_error is True
    assert result.matches == []


def test_selection_explanation_reconstructs_mmr_winners_independently(brain_home):
    for title, body in (
        ("Selection first", "bounded selection marker alpha repeated topic"),
        ("Selection neighbor", "bounded selection marker alpha repeated topic nearby"),
        ("Selection contrast", "bounded selection marker beta independent discovery"),
    ):
        mid = add_memory(brain_home, title, body)
        curate(brain_home, mid, status="current")

    result = HybridCascadeRetriever().retrieve(
        brain_home, "bounded selection marker", top_k=2, lambda_param=0.4
    )
    evidence = result.to_dict()["explanation"]
    candidates = {row["memory_id"]: row for row in evidence["candidates"]}
    assert evidence["candidate_count"] >= 2
    assert all(row["current_version"] for row in candidates.values())

    seed = min(
        candidates.values(),
        key=lambda row: tuple(
            value if value is not None else float("inf") for value in row["rank_key"]
        ),
    )
    reconstructed = [seed["memory_id"]]
    for step in evidence["selection_steps"]:
        remaining = {
            item["memory_id"]: item
            for item in step["candidates"]
            if item["memory_id"] not in reconstructed
        }
        winner = min(
            remaining.values(),
            key=lambda item: (
                -(
                    evidence["parameters"]["lambda_param"]
                    * candidates[item["memory_id"]]["candidate_score"]
                    - (1 - evidence["parameters"]["lambda_param"]) * item["max_token_jaccard"]
                ),
                tuple(
                    value if value is not None else float("inf")
                    for value in candidates[item["memory_id"]]["rank_key"]
                ),
            ),
        )
        assert step["selected_id"] == winner["memory_id"]
        reconstructed.append(winner["memory_id"])
    assert reconstructed == [match.memory_id for match in result.matches]
    assert evidence["omitted"] == result.to_dict()["omitted"]


def test_archived_history_does_not_enter_active_explanation(brain_home):
    active = add_memory(
        brain_home, "Active migration note", "history isolation marker", grade="VERIFIED"
    )
    curate(brain_home, active, status="current")
    archived = add_memory(
        brain_home, "Prohibited archived title", "history isolation marker", grade="VERIFIED"
    )
    curate(brain_home, archived, status="archived")

    result = HybridCascadeRetriever().retrieve(brain_home, "history isolation marker")

    assert [match.memory_id for match in result.matches] == [active]
    assert all(item["memory_id"] != archived for item in result.explanation["candidates"])
    assert all("title" not in item and "body" not in item for item in result.omitted)
    assert any(item["memory_id"] == archived for item in result.omitted)


@pytest.mark.parametrize("lambda_param", [-0.1, 1.1, float("nan"), float("inf"), "0.7", True])
def test_invalid_mmr_lambda_is_rejected(brain_home, lambda_param):
    with pytest.raises(BrainError):
        HybridCascadeRetriever().retrieve(
            brain_home, "bounded mmr lambda", lambda_param=lambda_param
        )


def test_non_positive_top_k_short_circuits_vectors(brain_home):
    called = False

    def vector_searcher(*_):
        nonlocal called
        called = True
        raise AssertionError("vector search must not run")

    result = HybridCascadeRetriever().retrieve(
        brain_home, "bounded top k", top_k=0, vector_searcher=vector_searcher
    )
    assert result.matches == []
    assert result.reason == "NO_RELEVANT_MEMORY"
    assert called is False


def test_mmr_equal_scores_use_authority_then_memory_id():
    advisory = RetrievalMatch(
        "mem-a",
        "advisory",
        0.8,
        RetrievalTier.TIER_2_LEXICAL_FTS5,
        raw_row={"authority_ceiling": "advisory"},
    )
    policy = RetrievalMatch(
        "mem-z",
        "policy",
        0.8,
        RetrievalTier.TIER_2_LEXICAL_FTS5,
        raw_row={"authority_ceiling": "policy"},
    )
    assert apply_mmr([advisory, policy], top_k=1)[0].memory_id == "mem-z"
