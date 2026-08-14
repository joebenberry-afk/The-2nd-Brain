"""Tests for the semantic memory cortex (Phase 10)."""

import re
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import semantic
from second_brain.errors import BrainError

_ID_RE = re.compile(r"^mem-[0-9a-f]{12}$")

SRC1 = [{"ref": "episodes/success-20260814-abc", "kind": "episode"}]
SRC2 = [{"ref": "decisions/2026-08-14-build-decisions.md", "kind": "decision"}]


def _add(home, title="WAL restore safety", body="never leave -wal next to a restored DB", **kw):
    return semantic.add_memory(home, title, body, **kw)


# ---------------------------------------------------------------------------
# Add / read roundtrip
# ---------------------------------------------------------------------------


def test_add_read_roundtrip(brain_home):
    mid = _add(
        brain_home,
        scope="project",
        project_id="proj-a",
        grade="INFERRED",
        sources=SRC1,
        summary="restore hygiene rule",
    )
    assert _ID_RE.match(mid)
    path = brain_home / "memory" / "semantic" / f"{mid}.md"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert f"id: {mid}" in body
    assert "title: WAL restore safety" in body
    assert "scope: project" in body
    assert "status: candidate" in body
    assert "grade: INFERRED" in body
    assert "version: 1" in body
    assert "never leave -wal next to a restored DB" in body

    shown = semantic.show_memory(brain_home, mid)
    assert shown["row"]["memory_id"] == mid
    assert shown["row"]["evidence_grade"] == "INFERRED"  # never presented wrongly
    assert shown["row"]["summary"] == "restore hygiene rule"
    assert shown["row"]["current_version"] == 1
    assert shown["row"]["strength"] == 0.5 and shown["row"]["stability"] == 0.5
    assert shown["path"] == str(path)
    assert shown["body"] == body
    assert semantic._sources(brain_home, mid)[0]["ref"] == SRC1[0]["ref"]


def test_add_validation(brain_home):
    with pytest.raises(BrainError, match="title"):
        _add(brain_home, title="  ")
    with pytest.raises(BrainError, match="body"):
        _add(brain_home, body="   ")
    with pytest.raises(BrainError, match="scope"):
        _add(brain_home, scope="globalx")
    with pytest.raises(BrainError, match="grade"):
        _add(brain_home, grade="PROVEN")
    with pytest.raises(BrainError, match="source kind"):
        _add(brain_home, sources=[{"ref": "x", "kind": "bogus"}])
    with pytest.raises(BrainError, match="sources"):
        _add(brain_home, sources="not-a-list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Curate / grade transitions
# ---------------------------------------------------------------------------


def test_grade_one_step_upgrades(brain_home):
    mid = _add(brain_home, grade="INFERRED")
    semantic.curate(brain_home, mid, grade="OBSERVED")
    semantic.curate(brain_home, mid, grade="TESTED")
    semantic.curate(brain_home, mid, grade="VERIFIED")
    row = semantic.show_memory(brain_home, mid)["row"]
    assert row["evidence_grade"] == "VERIFIED"
    assert row["last_verified_at"]  # verify=True default sets it


def test_grade_jump_rejected(brain_home):
    mid = _add(brain_home, grade="INFERRED")
    with pytest.raises(BrainError, match="not allowed"):
        semantic.curate(brain_home, mid, grade="VERIFIED")  # jump of two steps
    with pytest.raises(BrainError, match="not allowed"):
        semantic.curate(brain_home, mid, grade="TESTED")  # jump of two steps


def test_downgrade_only_reject_or_historical(brain_home):
    mid = _add(brain_home, grade="VERIFIED")
    semantic.curate(brain_home, mid, grade="VERIFIED", verify=True)  # same grade ok
    with pytest.raises(BrainError, match="not allowed"):
        semantic.curate(brain_home, mid, grade="OBSERVED")  # plain downgrade
    semantic.curate(brain_home, mid, grade="REJECTED")  # anywhere
    mid2 = _add(brain_home, title="Another", grade="VERIFIED")
    semantic.curate(brain_home, mid2, grade="HISTORICAL")  # downgrade to historical ok
    assert semantic.show_memory(brain_home, mid2)["row"]["evidence_grade"] == "HISTORICAL"


def test_curate_verify_flag(brain_home):
    mid = _add(brain_home, grade="TESTED")
    semantic.curate(brain_home, mid, grade="VERIFIED", verify=False)
    assert semantic.show_memory(brain_home, mid)["row"]["last_verified_at"] is None


def test_curate_status_and_sources_append(brain_home):
    mid = _add(brain_home, sources=SRC1)
    semantic.curate(brain_home, mid, status="current", sources=SRC2)
    row = semantic.show_memory(brain_home, mid)["row"]
    assert row["status"] == "current"
    refs = [s["ref"] for s in semantic._sources(brain_home, mid)]
    assert refs == [SRC1[0]["ref"], SRC2[0]["ref"]]
    with pytest.raises(BrainError, match="status"):
        semantic.curate(brain_home, mid, status="bogus")


# ---------------------------------------------------------------------------
# Supersede / history
# ---------------------------------------------------------------------------


def test_supersede_preserves_history(brain_home):
    mid = _add(brain_home, title="Old title")
    v1_path = brain_home / "memory" / "semantic" / f"{mid}.md"
    v1_body = v1_path.read_text(encoding="utf-8")

    v2 = semantic.supersede(
        brain_home,
        mid,
        new_title="New title",
        new_body="updated body",
        change_note="repo contradicts the old rule",
        new_sources=SRC2,
    )
    assert v2 == 2
    v2_path = brain_home / "memory" / "semantic" / f"{mid}__v2.md"
    assert v2_path.is_file()
    assert v1_path.read_text(encoding="utf-8") == v1_body  # v1 untouched
    assert "updated body" in v2_path.read_text(encoding="utf-8")
    assert "version: 2" in v2_path.read_text(encoding="utf-8")

    row = semantic.show_memory(brain_home, mid)["row"]
    assert row["current_version"] == 2
    assert row["title"] == "New title"
    assert row["body_path"].endswith(f"{mid}__v2.md")

    hist = semantic.history(brain_home, mid)
    assert [h["version"] for h in hist] == [1, 2]
    assert hist[0]["change_note"] == "repo contradicts the old rule"
    assert hist[0]["body_path"].endswith(f"{mid}.md")
    assert hist[1]["change_note"] is None  # current version
    assert hist[1]["body_path"].endswith(f"{mid}__v2.md")

    v3 = semantic.supersede(brain_home, mid, new_body="v3 body", change_note="narrowed")
    assert v3 == 3
    assert (brain_home / "memory" / "semantic" / f"{mid}__v3.md").is_file()
    assert [h["version"] for h in semantic.history(brain_home, mid)] == [1, 2, 3]


def test_supersede_unknown_raises(brain_home):
    with pytest.raises(BrainError, match="Unknown memory"):
        semantic.supersede(brain_home, "mem-000000000000", new_body="x", change_note="c")
    with pytest.raises(BrainError, match="change_note"):
        semantic.supersede(brain_home, _add(brain_home), new_body="x", change_note="  ")


# ---------------------------------------------------------------------------
# Contradictions / search / list
# ---------------------------------------------------------------------------


def test_contradictions_detection(brain_home):
    a = _add(brain_home, title="The rule", body="version one")
    b = _add(brain_home, title="the RULE", body="version two contradicts")  # same title, diff body
    same = _add(brain_home, title="The rule", body="version one")  # identical body -> not flagged
    rej = _add(brain_home, title="The rule", body="rejected version")
    semantic.curate(brain_home, rej, grade="REJECTED")
    _add(brain_home, title="Unrelated", body="x")

    pairs = semantic.contradictions(brain_home)
    # (a,b) and (same,b) flagged; (a,same) NOT flagged (identical bodies).
    flagged = {frozenset((p["memory_id_a"], p["memory_id_b"])) for p in pairs}
    assert flagged == {frozenset((a, b)), frozenset((same, b))}
    assert pairs[0]["title"] == "the rule"
    # Deterministic ordering: sorted by pair.
    assert [p["memory_id_a"] for p in pairs] == sorted(p["memory_id_a"] for p in pairs)


def test_contradictions_excludes_archived(brain_home):
    _add(brain_home, title="Same", body="one")
    mid2 = _add(brain_home, title="Same", body="two")
    semantic.curate(brain_home, mid2, status="archived")
    assert semantic.contradictions(brain_home) == []


def test_search_title_summary_body(brain_home):
    _add(brain_home, title="WAL hygiene", summary="restore safety", body="stale sidecar frames")
    _add(brain_home, title="Scout promotion", body="evidence map")
    assert len(semantic.search_memories(brain_home, "WAL")) == 1
    assert len(semantic.search_memories(brain_home, "SAFETY")) == 1  # summary
    assert len(semantic.search_memories(brain_home, "sidecar")) == 1  # body
    assert len(semantic.search_memories(brain_home, "zzz")) == 0
    with pytest.raises(BrainError, match="term"):
        semantic.search_memories(brain_home, " ")


def test_list_filters(brain_home):
    _add(brain_home, title="A", scope="project", project_id="p1")
    _add(brain_home, title="B", scope="project", project_id="p2")
    _add(brain_home, title="C", scope="domain", grade="TESTED")
    assert len(semantic.list_memories(brain_home)) == 3
    assert len(semantic.list_memories(brain_home, scope="project")) == 2
    assert len(semantic.list_memories(brain_home, project_id="p2")) == 1
    assert len(semantic.list_memories(brain_home, scope="domain")) == 1
    assert len(semantic.list_memories(brain_home, grade="TESTED")) == 1
    assert len(semantic.list_memories(brain_home, status="current")) == 0


def test_show_unknown_and_corrupt(brain_home):
    with pytest.raises(BrainError, match="Unknown memory"):
        semantic.show_memory(brain_home, "mem-000000000000")
    mid = _add(brain_home)
    path = brain_home / "memory" / "semantic" / f"{mid}.md"
    path.write_text("garbage without frontmatter", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        semantic.show_memory(brain_home, mid)
    assert str(path) in str(exc.value)
    path.unlink()
    with pytest.raises(BrainError, match="file missing"):
        semantic.show_memory(brain_home, mid)


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------

_UPGRADES = {"INFERRED": "OBSERVED", "OBSERVED": "TESTED", "TESTED": "VERIFIED"}


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(st.sampled_from(("add", "upgrade", "reject", "supersede")), min_size=1, max_size=12)
)
def test_random_memory_sequences_consistent(brain_home, ops):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    mid: str | None = None
    for index, op in enumerate(ops):
        if op == "add":
            mid = semantic.add_memory(home, f"Title {index}", f"body {index}", grade="INFERRED")
        elif mid is None:
            continue
        elif op == "upgrade":
            grade = semantic.show_memory(home, mid)["row"]["evidence_grade"]
            if grade in _UPGRADES:
                semantic.curate(home, mid, grade=_UPGRADES[grade])
        elif op == "reject":
            semantic.curate(home, mid, grade="REJECTED")
        else:
            semantic.supersede(home, mid, new_body=f"body v{index}", change_note=f"note {index}")
        # Consistency invariants after every op.
        row = semantic.show_memory(home, mid)["row"]
        files = sorted((home / "memory" / "semantic").glob(f"{mid}*.md"))
        assert len(files) == row["current_version"], (len(files), row["current_version"])
        hist = semantic.history(home, mid)
        assert [h["version"] for h in hist] == list(range(1, row["current_version"] + 1))
        for h in hist:
            assert (home / h["body_path"]).exists()
