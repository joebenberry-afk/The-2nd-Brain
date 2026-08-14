"""Tests for the RTD artifact store and deterministic distillers (Phase 5)."""

import json
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from second_brain import artifacts
from second_brain.errors import BrainError


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Store / expand
# ---------------------------------------------------------------------------


def test_store_text_roundtrip(brain_home):
    text = "hello world\nsecond line"
    info = artifacts.store_text(brain_home, text, "generic", tool="pytest", session="sess-1")
    assert artifacts.expand(brain_home, info["hash"]) == text.encode("utf-8")
    assert info["size"] == len(text.encode("utf-8"))
    assert info["kind"] == "generic"
    assert info["tool"] == "pytest"
    assert info["handle"] == f"[brain-artifact:sha256:{info['hash']}]"
    assert info["path"] == str(brain_home / "state" / "artifacts" / "blobs" / f"{info['hash']}.bin")

    meta = _read_json(brain_home / "state" / "artifacts" / "meta" / f"{info['hash']}.json")
    assert meta["v"] == 1
    assert meta["hash"] == info["hash"]
    assert meta["size"] == info["size"]
    assert meta["kind"] == "generic"
    assert meta["tool"] == "pytest"
    assert meta["session"] == "sess-1"
    assert meta["created_at"]
    blob = (brain_home / "state" / "artifacts" / "blobs" / f"{info['hash']}.bin").read_bytes()
    assert blob == text.encode("utf-8")


def test_handle_and_hint_constants(brain_home):
    info = artifacts.store_text(brain_home, "abc", "generic")
    h = info["hash"]
    assert artifacts.make_handle(h) == "[brain-artifact:sha256:" + h + "]"
    assert artifacts.recover_hint(h) == "Full output recoverable: /brain-expand " + h[:12]
    assert artifacts.HANDLE_TEMPLATE == "[brain-artifact:sha256:{hash}]"


def test_store_file_exact_bytes(brain_home, tmp_path):
    data = b"caf\xc3\xa9 \xff\xfe \x00 tail\n"
    target = tmp_path / "weird.bin"
    target.write_bytes(data)
    info = artifacts.store_file(brain_home, target, "test-log", tool="some-tool")
    assert artifacts.expand(brain_home, info["hash"]) == data
    assert info["size"] == len(data)
    assert isinstance(info["distilled"], str)  # decoded utf-8 errors=replace
    assert info["distilled"]  # non-empty


def test_store_file_missing_raises(brain_home, tmp_path):
    with pytest.raises(BrainError, match="Cannot read"):
        artifacts.store_file(brain_home, tmp_path / "nope.txt", "generic")


def test_prefix_expansion_unique(brain_home):
    text = "unique artifact content"
    info = artifacts.store_text(brain_home, text, "generic")
    expected = text.encode("utf-8")
    assert artifacts.expand(brain_home, info["hash"][:8]) == expected
    assert artifacts.expand(brain_home, info["hash"][:12]) == expected
    assert artifacts.expand(brain_home, info["hash"]) == expected
    assert artifacts.expand(brain_home, info["hash"].upper()) == expected


def test_prefix_expansion_ambiguous(brain_home):
    # Two meta files sharing an 8-char prefix -> ambiguous.
    meta_dir = brain_home / "state" / "artifacts" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("ac", "ad"):
        meta_dir.joinpath(f"{'ab' * 31}{suffix}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BrainError, match="Ambiguous"):
        artifacts.expand(brain_home, "ab" * 4)


def test_expand_unknown_and_invalid(brain_home):
    with pytest.raises(BrainError, match="Unknown"):
        artifacts.expand(brain_home, "f" * 64)
    with pytest.raises(BrainError, match="Unknown"):
        artifacts.expand(brain_home, "f" * 7)  # too short
    with pytest.raises(BrainError, match="Unknown"):
        artifacts.expand(brain_home, "z" * 8)  # not hex
    with pytest.raises(BrainError, match="Unknown"):
        artifacts.expand(brain_home, "f" * 65)  # too long
    with pytest.raises(BrainError):
        artifacts.expand(brain_home, "")


def test_store_twice_idempotent_then_collision(brain_home):
    text = "same content"
    first = artifacts.store_text(brain_home, text, "generic")
    second = artifacts.store_text(brain_home, text, "generic")
    assert first["hash"] == second["hash"]
    assert first["path"] == second["path"]
    meta_dir = brain_home / "state" / "artifacts" / "meta"
    blob_dir = brain_home / "state" / "artifacts" / "blobs"
    assert len(list(meta_dir.glob("*.json"))) == 1
    assert len(list(blob_dir.glob("*.bin"))) == 1

    # Corrupt the stored blob; the next identical store must refuse to overwrite.
    blob = blob_dir / f"{first['hash']}.bin"
    blob.write_bytes(b"corrupted!")
    with pytest.raises(BrainError, match="sha256 collision"):
        artifacts.store_text(brain_home, text, "generic")
    assert blob.read_bytes() == b"corrupted!"  # never overwritten

    # Meta present but blob gone -> corrupt store error.
    blob.unlink()
    with pytest.raises(BrainError, match="blob is missing"):
        artifacts.store_text(brain_home, text, "generic")


def test_list_artifacts_newest_first(brain_home):
    infos = []
    for i in range(4):
        infos.append(artifacts.store_text(brain_home, f"artifact {i}", "generic"))
    listed = artifacts.list_artifacts(brain_home)
    assert [m["hash"] for m in listed] == [i["hash"] for i in reversed(infos)]
    assert all(m["v"] == 1 for m in listed)
    assert listed[0]["created_at"] >= listed[-1]["created_at"]


def test_list_artifacts_empty(brain_home):
    assert artifacts.list_artifacts(brain_home) == []


def test_corrupt_meta_raises(brain_home):
    meta_dir = brain_home / "state" / "artifacts" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    bad = meta_dir / ("c" * 64 + ".json")
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BrainError) as exc:
        artifacts.list_artifacts(brain_home)
    assert str(bad) in str(exc.value)


def test_store_validates_params(brain_home):
    with pytest.raises(BrainError, match="kind"):
        artifacts.store_text(brain_home, "x", "   ")
    with pytest.raises(BrainError, match="tool"):
        artifacts.store_text(brain_home, "x", "generic", tool=5)  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="session"):
        artifacts.store_text(brain_home, "x", "generic", session=3)  # type: ignore[arg-type]
    with pytest.raises(BrainError, match="text"):
        artifacts.store_text(brain_home, 42, "generic")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Distillers (golden)
# ---------------------------------------------------------------------------

PYTEST_SAMPLE = """\
============================= test session starts =============================
collected 5 items

tests/test_a.py ..F.
tests/test_b.py .E

=================================== FAILURES ===================================
____ test_foo ____
tests/test_a.py:12: in test_foo
    assert 1 == 2
E   AssertionError: boom

FAILED tests/test_a.py::test_foo - AssertionError: boom
ERROR tests/test_b.py::test_bar - OSError: nope
=========================== short test summary info ===========================
3 passed, 2 failed, 1 error, 4 skipped in 5.32s
=============================== 2 failed, 1 error in 5.32s =====================
"""

GOLDEN_PYTEST = (
    "pytest: 3 passed, 2 failed, 1 errors, 4 skipped\n"
    "Failures:\n"
    "  FAILED tests/test_a.py::test_foo - AssertionError: boom\n"
    "  ERROR tests/test_b.py::test_bar - OSError: nope"
)


def test_distill_pytest_golden():
    assert artifacts.distill_pytest(PYTEST_SAMPLE) == GOLDEN_PYTEST
    # Same via the router.
    assert artifacts.distill(PYTEST_SAMPLE, "pytest") == GOLDEN_PYTEST


def test_distill_pytest_partial_summary():
    assert artifacts.distill_pytest("some output\n3 passed in 0.5s") == (
        "pytest: 3 passed, 0 failed, 0 errors, 0 skipped"
    )
    assert artifacts.distill_pytest("2 failed in 1.2s") == (
        "pytest: 0 passed, 2 failed, 0 errors, 0 skipped"
    )


def test_distill_pytest_fallback_to_generic():
    text = "random output\nwithout any pytest summary markers\n"
    assert artifacts.distill_pytest(text) == artifacts.distill_generic(text)
    assert artifacts.distill(text, "pytest") == artifacts.distill_generic(text)


def test_distill_pytest_failure_limit_10():
    text = "1 passed, 2 failed in 1s\n" + "\n".join(
        f"FAILED tests/test_{i:02d}.py::test_x - boom" for i in range(15)
    )
    out = artifacts.distill_pytest(text)
    assert out.count("\n  FAILED ") == 10


def test_distill_git_golden():
    text = "a1b2c3d Fix the bug\ne4f5g6h Add feature\n"
    assert artifacts.distill_git(text) == (
        "git log: 2 entries\na1b2c3d Fix the bug\ne4f5g6h Add feature"
    )
    assert artifacts.distill(text, "git") == artifacts.distill_git(text)


def test_distill_git_many_entries():
    text = "\n".join(f"c{i:06x} commit subject {i}" for i in range(60))
    out = artifacts.distill_git(text)
    assert out.startswith("git log: 60 entries\n")
    assert "commit subject 9" in out
    assert "commit subject 59" not in out  # only first 50 lines
    assert len(out) <= 2000


def test_distill_generic_golden():
    text = "line1\nline2\nline3\nline4\nline5\nline6\nline7"
    expected = (
        "7 lines, 41 bytes\n"
        "head:\nline1\nline2\nline3\nline4\nline5\n"
        "tail:\nline3\nline4\nline5\nline6\nline7"
    )
    assert artifacts.distill_generic(text) == expected


def test_distill_routing_search_and_test_log():
    text = "some search output\nwith two lines\n"
    assert artifacts.distill(text, "search") == artifacts.distill_generic(text)
    assert artifacts.distill(text, "test-log") == artifacts.distill_generic(text)
    assert artifacts.distill(text, "unknown-kind") == artifacts.distill_generic(text)


def test_distill_max_chars_cap():
    big = ("x" * 5000) + "\n" + ("y" * 5000)
    out = artifacts.distill(big, "generic", max_chars=100)
    assert len(out) <= 100
    assert artifacts.distill(big, "generic") == artifacts.distill_generic(big)
    assert len(artifacts.distill_generic(big)) <= 2000


def test_distill_never_contains_timestamps():
    text = "ran at 2026-08-14T05:00:00+00:00\n3 passed in 5.32s\n"
    out = artifacts.distill_pytest(text)
    assert "2026-08-14" not in out
    assert "5.32s" not in out


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


@settings(
    max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.text())
def test_store_expand_roundtrip_random(brain_home, text):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    info = artifacts.store_text(home, text, "generic")
    assert artifacts.expand(home, info["hash"]) == text.encode("utf-8")
    assert info["size"] == len(text.encode("utf-8"))


@given(st.text(), st.integers(min_value=10, max_value=3000))
def test_distill_generic_deterministic_property(text, max_chars):
    assert artifacts.distill_generic(text) == artifacts.distill_generic(text)
    out = artifacts.distill(text, "generic", max_chars=max_chars)
    assert len(out) <= max_chars


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.text(min_size=1), min_size=1, max_size=5))
def test_prefix_lookup_property(brain_home, texts):
    home = brain_home / uuid.uuid4().hex  # one fresh Brain per generated input
    by_hash = {}
    for text in texts:
        info = artifacts.store_text(home, text, "generic")
        by_hash[info["hash"]] = text.encode("utf-8")
    for h in by_hash:
        assert artifacts.expand(home, h) == by_hash[h]
        try:
            got = artifacts.expand(home, h[:12])
        except BrainError:
            continue  # ambiguous prefix: acceptable outcome
        assert got == by_hash[h]  # never wrong bytes
