"""Tests for Hybrid Multi-Tier Retrieval & Cascade (Plan §9)."""

import json
import os
import subprocess
import sys

from second_brain import semantic
from second_brain.hybrid_retrieval import (
    HybridCascadeRetriever,
    RetrievalTier,
)
from second_brain.semantic import add_memory, curate


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
            "schema_version = 2\n[gate]\nrollout = \"ACTIVE\"\n",
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
            "schema_version = 2\n[gate]\nrollout = \"ACTIVE\"\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            semantic,
            "search_memories",
            lambda *_a, **_kw: [{"memory_id": "mem-policy", "title": "Policy", "_score": 0.75}],
        )
        result = HybridCascadeRetriever().retrieve(
            brain_home, "policy query", lane="policy"
        )
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
        vector_called = False

        def mock_vector_searcher(query: str, project_id: str | None):
            nonlocal vector_called
            vector_called = True
            return [
                {
                    "memory_id": "mem-vector-99",
                    "title": "Vector Fallback Memory",
                    "score": 0.88,
                    "summary": "Dense semantic match",
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
        assert res.matches[0].memory_id == "mem-vector-99"


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
            if res.tier_resolved in (
                RetrievalTier.TIER_0_EXACT_REF,
                RetrievalTier.TIER_1_METADATA_FILTER,
                RetrievalTier.TIER_2_LEXICAL_FTS5,
            ) and not res.vector_invoked:
                tier_0_2_count += 1

        ratio = tier_0_2_count / total_queries
        # Gate Requirement: >= 80% (0.80) of routine queries resolve in Tiers 0-2
        assert ratio >= 0.80
        assert tier_0_2_count == 8  # 8 out of 10 resolved in Tiers 0-2 without vectors!


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
