"""Tests for the Intent Verifier brief builder (Phase 7)."""

import subprocess

import pytest

from second_brain import verify
from second_brain import working_set as ws
from second_brain.errors import BrainError


def _commit_repo(repo):
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)


def _dirty(repo):
    """Make tracked-file changes that git diff will show."""
    _commit_repo(repo)
    (repo / "README.md").write_text("# repo\nchanged line\n", encoding="utf-8")
    (repo / "feature.py").write_text("def f():\n    return 1\n", encoding="utf-8")


def _capsule(brain_home, sid="s1", files=("README.md", "feature.py"), constraints=("stdlib only",)):
    ws.init_capsule(brain_home, sid, "Verify the patch")
    ws.update_capsule(brain_home, sid, files_touched=list(files), constraints=list(constraints))
    return sid


def _build(brain_home, repo, sid="s1"):
    path = verify.build_verifier_brief(brain_home, sid, repo)
    return path, path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structure and ordering
# ---------------------------------------------------------------------------


def test_section_order_and_content(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Patch must add the feature", importance="critical")
    ws.add_evidence(brain_home, "s1", "REQ-001", "targeted test passes")
    path, text = _build(brain_home, repo)

    idx = {
        name: text.index(f"# {name}")
        for name in (
            "Backward Reconstruction",
            "Diff",
            "Requirements",
            "Constraints",
            "Validation Evidence",
            "Verifier Questions",
        )
    }
    assert idx["Backward Reconstruction"] < idx["Diff"] < idx["Requirements"]
    assert idx["Requirements"] < idx["Constraints"] < idx["Validation Evidence"]
    assert idx["Validation Evidence"] < idx["Verifier Questions"]

    assert "## Backward Reconstruction" in text
    assert "diff --git" in text  # real diff body present
    assert "- REQ-001 [critical/unverified] Patch must add the feature" in text
    assert "- stdlib only" in text
    assert "REQ-001:" in text and "targeted test passes" in text
    for question in verify.VERIFIER_QUESTIONS:
        assert question in text
    assert "session: s1" in text
    assert "generated_at:" in text
    assert f"repo: {repo}" in text
    assert path.parent == brain_home / "outputs" / "verification"
    assert path.name == "s1.md"


def test_diff_section_precedes_requirements(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Some requirement")
    _, text = _build(brain_home, repo)
    diff_pos = text.index("# Diff")
    req_pos = text.index("# Requirements")
    body_pos = text.index("diff --git")
    req_line = text.index("Some requirement")
    assert diff_pos < req_pos
    assert body_pos < req_line  # the diff body itself precedes the requirement text


def test_solver_reasoning_excluded(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.update_capsule(
        brain_home,
        "s1",
        current_hypotheses=["SECRETHYP"],
        decisions_this_session=["SECRETDEC"],
        next_action="SECRETNEXT",
        open_questions=["SECRETOPEN"],
    )
    _, text = _build(brain_home, repo)
    for marker in ("SECRETHYP", "SECRETDEC", "SECRETNEXT", "SECRETOPEN"):
        assert marker not in text


def test_missing_capsule_raises(brain_home, repo):
    with pytest.raises(BrainError):
        verify.build_verifier_brief(brain_home, "nosession", repo)


# ---------------------------------------------------------------------------
# Fallbacks and determinism
# ---------------------------------------------------------------------------


def test_none_fallbacks(brain_home, repo):
    _capsule(brain_home, files=(), constraints=())  # no files, no constraints, no ledger
    _, text = _build(brain_home, repo)
    assert "# Diff\n\n(no files recorded)" in text
    assert "# Requirements\n\n(none)" in text
    assert "# Constraints\n\n(none)" in text
    assert "# Validation Evidence\n\n(none)" in text


def test_git_errors_graced(brain_home, tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    (plain / "a.txt").write_text("x", encoding="utf-8")
    _capsule(brain_home, files=("a.txt",), constraints=())
    _, text = _build(brain_home, plain)
    assert "(diff unavailable" in text


def test_determinism_identical_except_generated_at(brain_home, repo):
    _dirty(repo)
    _capsule(brain_home)
    ws.add_requirement(brain_home, "s1", "Req one")
    ws.add_evidence(brain_home, "s1", "REQ-001", "evidence one")
    _, first = _build(brain_home, repo)
    _, second = _build(brain_home, repo)

    def strip(text):
        return "\n".join(line for line in text.splitlines() if not line.startswith("generated_at:"))

    assert strip(first) == strip(second)


def test_truncated_diff(brain_home, repo):
    _commit_repo(repo)
    big = repo / "big.py"
    big.write_text("one line\n", encoding="utf-8")
    subprocess.run(["git", "add", "big.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add big"], cwd=repo, check=True, capture_output=True)
    big.write_text("".join(f"line {i}\n" for i in range(500)), encoding="utf-8")
    _capsule(brain_home, files=("big.py",), constraints=())
    _, text = _build(brain_home, repo)
    diff_block = text.split("# Diff", 1)[1].split("# Requirements", 1)[0]
    diff_lines = [line for line in diff_block.splitlines() if line.strip()]
    assert len(diff_lines) <= verify.MAX_DIFF_LINES
