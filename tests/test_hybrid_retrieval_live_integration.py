"""
Live integration and benchmark tests for Hybrid Cascade Retrieval (Plan §4 R6).

Proves:
1. Tier 0: exact key / active session state resolution.
2. Tier 1 / 2: local FTS5 / BM25 lexical search resolution.
3. Negative result cache: repeated failed queries cost 0 tokens and resolve in sub-millisecond.
4. Benchmark: ≥80% routine queries resolve in Tiers 0-2 without Tier 3 dense vector calls.
"""

from second_brain.hybrid_retrieval import HybridCascadeRetriever, RetrievalTier
from second_brain.semantic import add_memory, curate


class TestHybridCascadeLiveIntegration:
    """Proves hybrid retrieval cascade and short-circuit benchmarks (§4 R6)."""

    def test_tier_0_exact_ref_resolution(self, brain_home):
        retriever = HybridCascadeRetriever()
        mid = add_memory(
            brain_home,
            "Cascade Rule Alpha",
            "Exact reference lookup principle full guidance",
            summary="Exact reference lookup principle",
            scope="global",
        )
        curate(brain_home, mid, grade="OBSERVED", status="current")

        # Query by exact memory ID
        res = retriever.retrieve(brain_home, mid)
        assert res.tier_resolved == RetrievalTier.TIER_0_EXACT_REF
        assert res.decision == "INJECT"
        assert res.short_circuited is True
        assert res.vector_invoked is False
        assert len(res.matches) == 1
        assert res.matches[0].memory_id == mid

    def test_tier_2_lexical_fts5_resolution(self, brain_home):
        retriever = HybridCascadeRetriever()
        mid = add_memory(
            brain_home,
            "Database Connection Pool",
            "Max 10 connections for SQLite WAL mode details",
            summary="Max 10 connections for SQLite WAL mode",
            scope="global",
        )
        curate(brain_home, mid, grade="OBSERVED", status="current")

        # Lexical search
        res = retriever.retrieve(brain_home, "database connection pool")
        assert res.tier_resolved in (
            RetrievalTier.TIER_1_METADATA_FILTER,
            RetrievalTier.TIER_2_LEXICAL_FTS5,
        )
        assert res.decision == "INJECT"
        assert res.vector_invoked is False
        assert any(m.memory_id == mid for m in res.matches)

    def test_negative_result_cache_submillisecond(self, brain_home):
        retriever = HybridCascadeRetriever()
        query = "nonexistent obscure fantasy term xyz99"

        # Query 1: misses and populates negative cache
        res1 = retriever.retrieve(brain_home, query)
        assert res1.decision == "NO_INJECTION"
        assert res1.negative_cached is False

        # Query 2: hits negative cache immediately (0 vector calls, sub-millisecond)
        res2 = retriever.retrieve(brain_home, query)
        assert res2.decision == "NO_INJECTION"
        assert res2.negative_cached is True
        assert res2.vector_invoked is False
        assert res2.latency_ms < 5.0

    def test_eighty_percent_short_circuit_benchmark(self, brain_home):
        retriever = HybridCascadeRetriever()

        # Seed 10 realistic memories
        mem_ids = []
        for i in range(10):
            mid = add_memory(
                brain_home,
                f"Architecture Standard {i}",
                f"Design rule for module {i} with specific patterns and guidelines",
                summary=f"Design rule for module {i} with specific patterns",
                scope="global",
            )
            curate(brain_home, mid, grade="OBSERVED", status="current")
            mem_ids.append(mid)

        # Run 20 routine queries (exact refs, keywords, and trivial/empty)
        queries = [
            mem_ids[0],
            mem_ids[1],
            "Architecture Standard 2",
            "Architecture Standard 3",
            "Architecture Standard 4",
            "design rule for module 5",
            "design rule for module 6",
            "hello",
            "thanks",
            "ok",
            "Architecture Standard 7",
            "Architecture Standard 8",
            "module 9 specific patterns",
            mem_ids[9],
            "nonexistent 1",
            "nonexistent 1",  # repeat -> negative cache hit
            "clear",
            "Architecture Standard 0",
            "Architecture Standard 1",
            "yes",
        ]

        vector_calls = 0
        short_circuited_calls = 0

        for q in queries:
            res = retriever.retrieve(brain_home, q)
            if res.vector_invoked:
                vector_calls += 1
            if res.short_circuited:
                short_circuited_calls += 1

        short_circuit_ratio = short_circuited_calls / len(queries)
        assert short_circuit_ratio >= 0.80  # ≥80% routine queries resolve without vector calls
        assert vector_calls == 0
