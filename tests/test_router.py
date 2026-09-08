"""Tests for the sparse skill router (Phase 17)."""

import json
import os
import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import episodes, router, skillforge
from second_brain.errors import BrainError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "router-tasks.json"
SKILL = "sqlite-migration-verifier"


def _episode(brain_home, summary, trigger="", counter="", lesson=""):
    sections = {}
    if trigger:
        sections["Trigger signals"] = trigger
    if counter:
        sections["Counter-signals"] = counter
    if lesson:
        sections["Reusable lesson"] = lesson
    return episodes.create_episode(brain_home, "correction", summary, sections=sections)


def _forge_and_shadow(brain_home, name=SKILL):
    eids = [
        _episode(
            brain_home,
            "sqlite migration failed on the second run",
            trigger="sqlite migration fail\nschema version mismatch",
            counter="fresh database\nno pending migration",
            lesson="verify migrations apply idempotently",
        ),
        _episode(
            brain_home,
            "pending migrations blocked the upgrade",
            trigger="pending migration\nmigration idempoten",
            counter="clean shutdown verified",
            lesson="check the schema_version table",
        ),
    ]
    skillforge.forge_candidate(brain_home, name, eids)
    # Empty eval lists still gate (validate + security always run).
    return skillforge.shadow_candidate(brain_home, name, trigger_cases=[], baseline_cases=[])


# ---------------------------------------------------------------------------
# Scoring math
# ---------------------------------------------------------------------------


def test_route_scoring_math(brain_home):
    _forge_and_shadow(brain_home)
    # trigger phrase + name bigram + procedure overlap, all positive
    result = router.route(
        brain_home, "sqlite migration verifier: pending migration blocking the upgrade"
    )
    assert result["scores"][SKILL] == round(router.POSITIVE_POINTS + router.NAME_BIGRAM_POINTS, 2)
    assert result["selected"] == [SKILL]
    # trigger only -> exactly POSITIVE_POINTS
    result = router.route(brain_home, "pending migration blocking the upgrade")
    assert result["scores"][SKILL] == router.POSITIVE_POINTS
    # name bigram only ("migration verifier") -> NAME_BIGRAM_POINTS, selected
    result = router.route(brain_home, "run the migration verifier on the patch")
    assert result["scores"][SKILL] == router.NAME_BIGRAM_POINTS
    assert result["selected"] == [SKILL]
    # generic name-token mention without bigram or trigger -> below threshold, not selected
    result = router.route(brain_home, "migration of the marketing website plan")
    assert result["selected"] == []


def test_negative_override_scores(brain_home):
    _forge_and_shadow(brain_home)
    # positive + negative + negative + procedure overlap -> strongly negative
    result = router.route(
        brain_home,
        "fresh database no pending migration blocking the upgrade, no pending migration blocking",
    )
    assert result["scores"][SKILL] < 0
    assert result["selected"] == []


def test_top_k_cap_and_score_filter(brain_home):
    _forge_and_shadow(brain_home)
    result = router.route(brain_home, "pending migrations are blocking the upgrade", max_active=1)
    assert result["selected"] == [SKILL]
    result = router.route(brain_home, "deploy the frontend build")
    assert result["selected"] == []


def test_route_deterministic(brain_home):
    _forge_and_shadow(brain_home)
    task = "sqlite migration failed with a schema version mismatch"
    assert router.route(brain_home, task) == router.route(brain_home, task)


def test_route_empty_shadow_dir(brain_home):
    result = router.route(brain_home, "any task at all")
    assert result == {"selected": [], "scores": {}, "shadow": True}


def test_route_validation(brain_home):
    # blank tasks route to nothing (shadow router never blocks on input)
    assert router.route(brain_home, "   ") == {"selected": [], "scores": {}, "shadow": True}
    assert router.route(brain_home, "\x85") == {"selected": [], "scores": {}, "shadow": True}
    with pytest.raises(BrainError, match="max_active"):
        router.route(brain_home, "x", max_active=0)


def test_natural_baseline_name_tokens(brain_home):
    _forge_and_shadow(brain_home)
    assert router.natural_baseline(brain_home, "migration of the marketing site") == [SKILL]
    assert router.natural_baseline(brain_home, "deploy the frontend build") == []
    # No shadow skills -> empty.
    assert router.natural_baseline(brain_home / "empty", "migration") == []


# ---------------------------------------------------------------------------
# Fixture eval + acceptance
# ---------------------------------------------------------------------------


def test_fixture_shape():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    assert len(tasks) >= 10
    with_expectations = [t for t in tasks if t.get("expect")]
    assert len(with_expectations) >= 4
    distractors = [t for t in tasks if not t.get("expect")]
    assert len(distractors) >= 2


def test_eval_router_acceptance(brain_home):
    _forge_and_shadow(brain_home)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = router.eval_router(brain_home, data["tasks"])
    # Acceptance (plan §113): lower trigger noise AND no f1 regression.
    assert result["router"]["noise"] <= result["natural"]["noise"]
    assert result["router"]["f1"] >= result["natural"]["f1"]
    # The router should be meaningfully better on this fixture.
    assert result["router"]["noise"] < result["natural"]["noise"]
    assert result["router"]["f1"] >= result["natural"]["f1"]


# ---------------------------------------------------------------------------
# Hypothesis: determinism under random tasks
# ---------------------------------------------------------------------------


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.text(min_size=1, max_size=80), min_size=0, max_size=8))
def test_route_random_deterministic(brain_home, texts):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    _forge_and_shadow(home, name="skill")
    for text in texts:
        assert router.route(home, text) == router.route(home, text)


# ---------------------------------------------------------------------------
# Phase 13: SKILL.md section cache + router.max_active config wiring
# ---------------------------------------------------------------------------


def _spy_skill_reads(monkeypatch):
    """Count Path.read_text calls on SKILL.md files (SKILL.md paths only)."""
    original = Path.read_text
    counter = {"reads": 0}

    def counting_read_text(self, *args, **kwargs):
        if str(self).endswith("SKILL.md"):
            counter["reads"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    return counter


def test_route_reads_each_skill_md_at_most_once_per_call(brain_home, monkeypatch):
    _forge_and_shadow(brain_home)
    counter = _spy_skill_reads(monkeypatch)
    result = router.route(brain_home, "sqlite migration failed with a schema version mismatch")
    # Previously the same SKILL.md was read TWICE per skill per call
    # (positive triggers + procedure); the cache must collapse it to one.
    assert counter["reads"] == 1
    assert result["selected"] == [SKILL]


def test_route_second_call_unchanged_files_zero_reads(brain_home, monkeypatch):
    _forge_and_shadow(brain_home)
    router.route(brain_home, "sqlite migration failed with a schema version mismatch")  # warm cache
    counter = _spy_skill_reads(monkeypatch)
    result = router.route(brain_home, "pending migration blocking the upgrade")
    assert counter["reads"] == 0
    assert result["selected"] == [SKILL]


def test_route_cache_invalidates_on_skill_md_change(brain_home, monkeypatch):
    _forge_and_shadow(brain_home)
    router.route(brain_home, "sqlite migration failed with a schema version mismatch")  # warm cache
    skill_md = brain_home / "skills" / "shadow" / SKILL / "SKILL.md"
    # Append a NEW Positive Triggers section with a brand-new phrase; the
    # router's section parser keys by heading, so the new heading replaces
    # the old trigger content after the file changes.
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8")
        + "\n# Positive Triggers\n- brand new trigger phrase\n",
        encoding="utf-8",
    )
    bumped = os.stat(skill_md).st_mtime_ns + 2_000_000  # guarantee a fresh mtime
    # ns= form: on Windows, passing ns ints through the seconds tuple
    # overflows the FILETIME conversion (WinError 87).
    os.utime(skill_md, ns=(bumped, bumped))
    counter = _spy_skill_reads(monkeypatch)
    result = router.route(brain_home, "brand new trigger phrase")
    assert counter["reads"] == 1  # stale cache entry re-read after mtime change
    assert result["selected"] == [SKILL]  # fresh content drives the score


def _forge_second_skill(brain_home, name="blocked-upgrade-verifier"):
    eids = [
        _episode(
            brain_home,
            "upgrade blocked by a pending operation",
            trigger="blocking the upgrade\nupgrade blocked",
            lesson="check what is blocking the upgrade",
        ),
    ]
    skillforge.forge_candidate(brain_home, name, eids)
    return skillforge.shadow_candidate(brain_home, name, trigger_cases=[], baseline_cases=[])


def test_router_max_active_honors_skills_toml(brain_home):
    _forge_and_shadow(brain_home)
    _forge_second_skill(brain_home)
    # Task that qualifies BOTH skills: skill1 via triggers/bigram (score 4.5),
    # second via trigger phrase "blocking the upgrade" (score 1.0).
    task = (
        "sqlite migration failed with a schema version mismatch and "
        "pending migration blocking the upgrade"
    )
    assert len(router.route(brain_home, task)["selected"]) == 2  # default cap (absent config -> 3)

    cfg = brain_home / "config" / "skills.toml"
    cfg.write_text("schema_version = 1\n[router]\nmax_active = 1\n", encoding="utf-8")
    selected = router.route(brain_home, task)["selected"]
    assert len(selected) == 1
    assert selected == [SKILL]  # highest-scoring skill wins the single slot

    # Invalid config values fall back to 3.
    cfg.write_text("schema_version = 1\n[router]\nmax_active = 0\n", encoding="utf-8")
    assert len(router.route(brain_home, task)["selected"]) == 2
    cfg.write_text('schema_version = 1\n[router]\nmax_active = "nope"\n', encoding="utf-8")
    assert len(router.route(brain_home, task)["selected"]) == 2
    cfg.write_text("schema_version = 1\n", encoding="utf-8")  # absent [router]
    assert len(router.route(brain_home, task)["selected"]) == 2


def test_router_max_active_explicit_override_beats_config(brain_home):
    _forge_and_shadow(brain_home)
    _forge_second_skill(brain_home)
    task = (
        "sqlite migration failed with a schema version mismatch and "
        "pending migration blocking the upgrade"
    )
    (brain_home / "config" / "skills.toml").write_text(
        "schema_version = 1\n[router]\nmax_active = 1\n", encoding="utf-8"
    )
    # CLI-style explicit cap overrides the config value.
    assert len(router.route(brain_home, task, max_active=3)["selected"]) == 2


def test_route_conservative_routing_unchanged_with_cache(brain_home, monkeypatch):
    _forge_and_shadow(brain_home)
    router.route(brain_home, "sqlite migration failed with a schema version mismatch")  # warm cache
    # Weak generic mention must still select NOTHING (thresholds untouched).
    assert router.route(brain_home, "migration of the marketing website plan")["selected"] == []
    # Cache contents do not leak across different tasks.
    assert router.route(brain_home, "deploy the frontend build")["selected"] == []
