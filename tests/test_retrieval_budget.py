"""Phases 10/11/12: contradiction surfacing, retrieval budget, config wiring."""

import os
import subprocess
import sys
from pathlib import Path

from second_brain import semantic

_CFG_DIR = "config"


def _add(home, title, body, **kw):
    return semantic.add_memory(home, title, body, **kw)


def _ids(rows):
    return [r["memory_id"] for r in rows]


def _write_retrieval_toml(home, text: str) -> None:
    (home / _CFG_DIR).mkdir(parents=True, exist_ok=True)
    (home / _CFG_DIR / "retrieval.toml").write_text(text, encoding="utf-8")


def _write_context_toml(home, text: str) -> None:
    (home / _CFG_DIR).mkdir(parents=True, exist_ok=True)
    (home / _CFG_DIR / "context.toml").write_text(text, encoding="utf-8")


_FAMILY_WORDS = ["alpha", "bravo", "charlie", "delta", "echo"]


def _ranked_family(home):
    """5 same-theme memories with DISTINCT bodies (separate dedupe families,
    equal relevance); the VERIFIED/current one is the clear top."""
    top = _add(
        home,
        title="Budget ceiling rule",
        body="wal frame budget ceiling journal note alpha",
        grade="VERIFIED",
    )
    semantic.curate(home, top, status="current")
    others = [
        _add(
            home,
            title=f"Budget note {i}",
            body=f"wal frame budget ceiling journal note {_FAMILY_WORDS[i + 1]}",
            grade="TESTED",
        )
        for i in range(4)
    ]
    for mid in others:
        semantic.curate(home, mid, status="current")
    return top, others


def test_contradiction_pair_marked_in_results(brain_home):
    a = _add(brain_home, title="WAL policy", body="wal journal mode is WAL", grade="VERIFIED")
    b = _add(brain_home, title="WAL policy", body="wal journal mode is DELETE", grade="VERIFIED")
    semantic.curate(brain_home, a, status="current")
    semantic.curate(brain_home, b, status="current")

    # default path: dedupe collapses the same-title family, but the surviving
    # representative must NOT silently hide the conflict
    rows = semantic.search_memories(brain_home, "wal journal", top_k=20)
    assert len(rows) == 1
    survivor = rows[0]
    assert survivor["memory_id"] in (a, b)
    assert survivor["contradiction_with"] == [a if survivor["memory_id"] == b else b]

    # comparison path: both sides returned, each marked with the other
    both = semantic.search_memories(
        brain_home, "wal journal", include_duplicates=True, top_k=20
    )
    by_id = {r["memory_id"]: r for r in both}
    assert a in by_id and b in by_id
    assert by_id[a]["contradiction_with"] == [b]
    assert by_id[b]["contradiction_with"] == [a]

    # linear fallback applies the same surfacing
    lin = semantic._search_linear(brain_home, "wal journal", include_duplicates=True, top_k=20)
    lin_by_id = {r["memory_id"]: r for r in lin}
    assert lin_by_id[a]["contradiction_with"] == [b]


def test_contradiction_marker_absent_for_identical_bodies(brain_home):
    _add(brain_home, title="WAL policy", body="wal journal mode is WAL", grade="VERIFIED")
    _add(brain_home, title="WAL policy", body="wal journal mode is WAL", grade="VERIFIED")
    rows = semantic.search_memories(brain_home, "wal journal", include_duplicates=True, top_k=20)
    for row in rows:
        assert "contradiction_with" not in row


def test_cli_prints_conflicting_evidence_block(brain_home):
    _add(brain_home, title="WAL policy", body="wal journal mode is WAL", grade="VERIFIED")
    _add(brain_home, title="WAL policy", body="wal journal mode is DELETE", grade="VERIFIED")
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    cmd = [
        sys.executable,
        "-m",
        "second_brain",
        "--home",
        str(brain_home),
        "memory",
        "search",
        "wal journal",
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert r.returncode == 0, r.stderr
    assert "Conflicting prior evidence:" in r.stdout
    assert "<->" in r.stdout


def test_top_k_trims_to_highest_scoring_rows(brain_home):
    top, others = _ranked_family(brain_home)
    rows = semantic.search_memories(brain_home, "wal frame", top_k=2)
    assert len(rows) == 2
    assert _ids(rows)[0] == top
    assert set(_ids(rows)) - {top} <= set(others)
    # default cap (no config): plan default 3
    rows = semantic.search_memories(brain_home, "wal frame")
    assert len(rows) == 3
    assert _ids(rows)[0] == top


def test_token_budget_trims_low_value_rows(brain_home):
    top, _ = _ranked_family(brain_home)
    # bodies are ~7 word-tokens; ceiling 8 keeps only the best row
    rows = semantic.search_memories(brain_home, "wal frame", top_k=10, max_tokens=8)
    assert len(rows) == 1
    assert _ids(rows)[0] == top
    # a generous budget keeps everything under top_k
    rows = semantic.search_memories(brain_home, "wal frame", top_k=10, max_tokens=10_000)
    assert len(rows) == 5
    assert _ids(rows)[0] == top
    # zero ceiling: only the best row
    rows = semantic.search_memories(brain_home, "wal frame", top_k=10, max_tokens=0)
    assert len(rows) == 1
    assert _ids(rows)[0] == top


def test_retrieval_toml_weights_reorder_results(brain_home):
    top, _ = _ranked_family(brain_home)
    assert _ids(semantic.search_memories(brain_home, "wal frame", top_k=5))[0] == top
    # demote VERIFIED below TESTED -> the TESTED rows now outrank the old top
    _write_retrieval_toml(
        brain_home,
        """schema_version = 1
[scoring]
max_results = 2
[scoring.weights]
grade_scores = { VERIFIED = 0.2, TESTED = 1.0 }
""",
    )
    rows = semantic.search_memories(brain_home, "wal frame")
    assert len(rows) == 2  # max_results wired
    assert _ids(rows)[0] != top
    # a second weight knob measurably moves the order back: decision boost
    # with a decision-proven target restores it to rank 1
    conn = __import__("second_brain.db", fromlist=["connect"]).connect(
        __import__("second_brain.paths", fromlist=["db_path"]).db_path(brain_home)
    )
    try:
        conn.execute(
            "UPDATE memories SET successful_retrieval_count = 5 WHERE memory_id = ?",
            (top,),
        )
        conn.commit()
    finally:
        conn.close()
    _write_retrieval_toml(
        brain_home,
        """schema_version = 1
[scoring]
max_results = 5
[scoring.weights]
decision_boost_per_hit = 10.0
decision_boost_cap = 50.0
""",
    )
    rows = semantic.search_memories(brain_home, "wal frame")
    assert _ids(rows)[0] == top


def test_retrieved_memory_pct_max_caps_token_budget(brain_home):
    top, _ = _ranked_family(brain_home)
    assert top
    # 0.005% of the 200k context window = 10 tokens -> only the best row fits
    _write_context_toml(
        brain_home,
        """schema_version = 1
[reserve]
retrieved_memory_pct_max = 0.005
""",
    )
    rows = semantic.search_memories(brain_home, "wal frame", top_k=10)
    assert len(rows) == 1
    assert _ids(rows)[0] == top


def test_absent_or_invalid_config_keeps_defaults(brain_home):
    _ranked_family(brain_home)
    baseline = _ids(semantic.search_memories(brain_home, "wal frame", top_k=10))
    # garbage TOML: fail open, identical behavior
    _write_retrieval_toml(brain_home, "this is [ not toml")
    _write_context_toml(brain_home, "also {{ not toml")
    assert _ids(semantic.search_memories(brain_home, "wal frame", top_k=10)) == baseline
    # invalid types fall back per-key
    _write_retrieval_toml(
        brain_home,
        """schema_version = 1
[scoring]
max_results = -5
[scoring.weights]
title_boost_exact = "nope"
grade_scores = 42
""",
    )
    assert _ids(semantic.search_memories(brain_home, "wal frame", top_k=10)) == baseline
    # invalid pct falls back to unlimited budget
    _write_context_toml(
        brain_home,
        """schema_version = 1
[reserve]
retrieved_memory_pct_max = 101
""",
    )
    assert _ids(semantic.search_memories(brain_home, "wal frame", top_k=10)) == baseline
