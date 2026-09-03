"""P0 write-back candidate tests (Phase 0D; plan §6.7, P0-G9/G10, §17.1).

`brainctl autoinject writeback` creates a CANDIDATE memory (never promoted
to truth): status candidate, grade OBSERVED, provenance pointing at the
session. T1.3 admits OBSERVED candidates as low-confidence context;
VERIFIED/TESTED candidates render HIGH confidence; the delivery ledger keeps
the same session lineage from re-injecting.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from second_brain import autoinject, semantic
from second_brain.contracts import BrainInjectionDecision

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    return subprocess.run(
        [sys.executable, "-m", "second_brain", "--home", str(home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=120,
    )


def _init(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr


def _inject(home: Path, task: str, session_id: str = "s1") -> BrainInjectionDecision:
    return autoinject.BrainLifecycle(home).prepare_injection(
        task,
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id=session_id,
        branch_id="main",
    )


def _writeback(
    home: Path,
    *,
    session_id: str = "s1",
    title: str = "Lesson: verify before retry",
    observation: str = "always verify external state before retrying",
    guidance: str = "verify then retry",
    evidence: str = '[{"ref": "tests/test_verify.py", "kind": "test"}]',
) -> dict:
    r = _run_cli(
        home,
        "autoinject",
        "writeback",
        "--session",
        session_id,
        "--project",
        "proj-a",
        "--title",
        title,
        "--observation",
        observation,
        "--guidance",
        guidance,
        "--evidence",
        evidence,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_writeback_creates_candidate_with_provenance(tmp_path) -> None:
    home = tmp_path / "brain"
    _init(home)
    out = _writeback(home)
    assert out["status"] == "candidate"
    assert out["memory_id"].startswith("mem-")
    shown = semantic.show_memory(home, out["memory_id"])
    row = shown["row"]
    assert row["status"] == "candidate"  # never promoted to truth
    assert row["evidence_grade"] == "OBSERVED"
    sources = semantic._sources(home, out["memory_id"])
    assert sources[0]["ref"] == "session:s1"  # provenance -> session
    assert any(s["ref"] == "tests/test_verify.py" for s in sources)


def test_observed_candidate_is_retrievable_with_low_confidence(tmp_path) -> None:
    home = tmp_path / "brain"
    _init(home)
    out = _writeback(home, observation="verify external state before retry")
    d = _inject(home, "verify external state before retry", session_id="fresh-s1")
    assert d.decision.value == "INJECT"
    assert d.selected_ids == [out["memory_id"]]


def test_verified_candidate_is_retrievable_fresh_session_g10(tmp_path) -> None:
    home = tmp_path / "brain"
    _init(home)
    out = _writeback(home, observation="verify external state before retry")
    # Grade ladder is one-step: OBSERVED -> TESTED -> VERIFIED.
    semantic.curate(home, out["memory_id"], grade="TESTED")
    semantic.curate(home, out["memory_id"], grade="VERIFIED")
    # Fresh session (different session id) retrieves the lesson (G10).
    d = _inject(home, "verify external state before retry", session_id="fresh-s2")
    assert d.decision.value == "INJECT"
    assert d.selected_ids == [out["memory_id"]]


def test_writeback_does_not_reinject_same_memory_lineage(tmp_path) -> None:
    home = tmp_path / "brain"
    _init(home)
    mid = semantic.add_memory(
        home, "Migration ordering", "apply migrations in numeric order",
        scope="project", project_id="proj-a", grade="TESTED",
    )
    semantic.curate(home, mid, status="current")
    first = _inject(home, "migration ordering", session_id="s1")
    assert first.decision.value == "INJECT"
    out = _writeback(home, session_id="s1", title="Outcome note", observation="migration ran clean")
    # Same session lineage: the delivered memory stays deduped, while the new
    # observed candidate is independently eligible under T1.3.
    second = _inject(home, "migration ordering", session_id="s1")
    assert second.decision.value == "INJECT"
    assert mid not in second.selected_ids
    assert out["memory_id"] in second.selected_ids

def test_writeback_evidence_dict_normalized(tmp_path) -> None:
    """T-G6-F4: --evidence accepts a plain dict {ref: kind} and normalizes to
    the canonical [{ref, kind}] list schema."""
    home = tmp_path / "brain"
    _init(home)
    r = _run_cli(
        home,
        "autoinject",
        "writeback",
        "--session",
        "s-ev",
        "--project",
        "proj-a",
        "--title",
        "Dict evidence lesson",
        "--observation",
        "dict form works",
        "--evidence",
        '{"tests/test_verify.py": "test", "docs/decisions/x.md": "decision"}',
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "candidate"
    sources = semantic._sources(home, out["memory_id"])
    pairs = {(s["ref"], s["kind"]) for s in sources}
    assert ("tests/test_verify.py", "test") in pairs
    assert ("docs/decisions/x.md", "decision") in pairs
    # list form stays canonical
    r2 = _run_cli(
        home,
        "autoinject",
        "writeback",
        "--session",
        "s-ev2",
        "--project",
        "proj-a",
        "--title",
        "List evidence lesson",
        "--observation",
        "list form stays",
        "--evidence",
        '[{"ref": "tests/test_db.py", "kind": "test"}]',
    )
    out2 = json.loads(r2.stdout)
    sources2 = semantic._sources(home, out2["memory_id"])
    pairs2 = {(s["ref"], s["kind"]) for s in sources2}
    assert ("tests/test_db.py", "test") in pairs2
