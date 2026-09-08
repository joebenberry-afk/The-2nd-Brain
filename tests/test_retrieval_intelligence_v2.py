"""Focused T7.3 Retrieval Intelligence 2.0 tests."""

from __future__ import annotations

from pathlib import Path

from second_brain import reconsolidation, semantic
from second_brain.hybrid_retrieval import HybridCascadeRetriever, RetrievalTier


def test_retrieval_exposes_score_components(brain_home: Path) -> None:
    """Every retrieval match exposes inspectable score components in structured and dict
    form."""
    mid = semantic.add_memory(
        brain_home,
        title="Cache Coherency Policy",
        body="Cache invalidation occurs on write to keep read replicas coherent.",
        scope="project",
        project_id="proj-cache",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, mid, status="current")
    reconsolidation.record_activation(brain_home, mid, "correct", kind="used")

    retriever = HybridCascadeRetriever()
    res = retriever.retrieve(brain_home, "cache invalidation coherency", project_id="proj-cache")

    assert len(res.matches) >= 1
    match = res.matches[0]
    comps = match.score_components
    expected_keys = {
        "relevance",
        "authority",
        "scope",
        "freshness",
        "contradiction",
        "activation_need",
        "diversity",
        "final_score",
    }
    assert expected_keys.issubset(comps.keys())
    for k in expected_keys:
        assert isinstance(comps[k], (int, float))

    # Emitted in dict form
    as_dict = match.to_dict()
    assert "score_components" in as_dict
    assert as_dict["score_components"]["relevance"] == round(comps["relevance"], 4)


def test_contradiction_is_surfaced(brain_home: Path) -> None:
    """Contradictions are explicitly surfaced in CascadeResult and RetrievalMatch, not
    averaged away."""
    mid = semantic.add_memory(
        brain_home,
        title="Memory Eviction Watermark",
        body="Eviction starts at 80% resident memory.",
        scope="project",
        project_id="proj-mem",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid, status="current")

    # Mark memory as contradicted
    reconsolidation.record_activation(brain_home, mid, "contradicted")

    retriever = HybridCascadeRetriever()
    res = retriever.retrieve(brain_home, "Memory Eviction Watermark", project_id="proj-mem")

    assert len(res.matches) >= 1
    match = res.matches[0]
    assert match.has_contradiction is True
    assert len(match.contradiction_details) >= 1
    assert "Contradiction count" in match.contradiction_details[0]

    # Explicitly surfaced at CascadeResult level
    assert len(res.contradictions) >= 1
    assert res.contradictions[0]["memory_id"] == mid
    assert res.to_dict()["contradictions"] == res.contradictions


def test_exact_ref_bypasses_relevance_not_authority(brain_home: Path) -> None:
    """Exact ID/reference lookup bypasses semantic scoring but strictly enforces
    authority safety."""
    # 1. Normal project-rule memory
    mid_rule = semantic.add_memory(
        brain_home,
        title="Valid Rule Reference",
        body="A verified rule that can be queried by ID.",
        scope="project",
        project_id="proj-safe",
        grade="VERIFIED",
        origin_class="TRUSTED_TEST",
    )
    semantic.curate(brain_home, mid_rule, status="current")

    retriever = HybridCascadeRetriever()

    # Exact ref lookup in semantic lane: passes with Tier 0 and score=1.0
    res_rule = retriever.retrieve(brain_home, mid_rule, project_id="proj-safe", lane="semantic")
    assert res_rule.tier_resolved == RetrievalTier.TIER_0_EXACT_REF
    assert res_rule.decision == "INJECT"
    assert res_rule.matches[0].score == 1.0

    # 2. Advisory model-inference memory queried in policy lane: MUST FAIL authority safety!
    mid_adv = semantic.add_memory(
        brain_home,
        title="Advisory Model Inference",
        body="An unpromoted model inference suggestion.",
        scope="project",
        project_id="proj-safe",
        grade="INFERRED",
        origin_class="MODEL_INFERENCE",
    )
    semantic.curate(brain_home, mid_adv, status="candidate")

    # Query exact ID in policy lane: authority violation
    res_adv = retriever.retrieve(brain_home, mid_adv, project_id="proj-safe", lane="policy")
    assert res_adv.decision == "NO_INJECTION"
    assert res_adv.reason == "AUTHORITY_VIOLATION"

    # 3. Rejected memory: MUST FAIL status safety
    mid_rej = semantic.add_memory(
        brain_home,
        title="Rejected Bad Advice",
        body="Incorrect advice that was rejected.",
        scope="project",
        project_id="proj-safe",
        grade="REJECTED",
    )
    res_rej = retriever.retrieve(brain_home, mid_rej, project_id="proj-safe")
    assert res_rej.decision == "NO_INJECTION"
    assert res_rej.reason == "EXCLUDED_STATUS"


def test_mmr_reduces_duplicate_topk(brain_home: Path) -> None:
    """MMR with lambda=0.7 reduces near-duplicate matches in favor of diverse relevant
    results."""
    # Memory A: PostgreSQL Connection Pooling
    mid_a = semantic.add_memory(
        brain_home,
        title="PostgreSQL Connection Pooling Setup",
        body="Configure PgBouncer pooling for PostgreSQL databases with 100 max connections.",
        scope="project",
        project_id="proj-db",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, mid_a, status="current")

    # Memory B: Near-duplicate of A (redundant)
    mid_b = semantic.add_memory(
        brain_home,
        title="PostgreSQL Connection Pool Guide",
        body="Configure PgBouncer pooling for PostgreSQL databases with 100 max connections.",
        scope="project",
        project_id="proj-db",
        grade="TESTED",
    )
    semantic.curate(brain_home, mid_b, status="current")

    # Memory C: Diverse database advice (Redis)
    mid_c = semantic.add_memory(
        brain_home,
        title="Redis Key Value Cache Configuration",
        body="Use Redis in-memory cache for fast session key-value storage and cache eviction.",
        scope="project",
        project_id="proj-db",
        grade="VERIFIED",
    )
    semantic.curate(brain_home, mid_c, status="current")

    retriever = HybridCascadeRetriever()
    res = retriever.retrieve(
        brain_home,
        "PostgreSQL Redis database cache pooling",
        project_id="proj-db",
        top_k=2,
        lambda_param=0.7,
    )

    matched_ids = [m.memory_id for m in res.matches]
    # Under MMR, the top 2 should include mid_a (highest score) and the diverse mid_c,
    # penalizing redundant mid_b!
    assert mid_a in matched_ids
    assert mid_c in matched_ids
    # Duplicate mid_b was demoted below top 2 by MMR diversity penalty
    assert mid_b not in matched_ids


def test_multiview_off_by_default(brain_home: Path) -> None:
    """Multi-view retrieval is disabled by default and only runs when explicitly
    requested."""
    retriever = HybridCascadeRetriever()
    assert retriever.multiview_enabled is False

    res = retriever.retrieve(brain_home, "routine system query")
    assert res.multiview_invoked is False
