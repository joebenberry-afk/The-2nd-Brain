"""Focused T1.4 evidence fingerprint/freshness contracts."""

import hashlib
import sqlite3
import subprocess
from pathlib import Path

from second_brain import autoinject, contracts, db, freshness, semantic


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, message: str = "fixture") -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", "commit", "-qm", message], cwd=repo, check=True, capture_output=True)
    return _git(repo, "rev-parse", "HEAD")


def _source(repo: Path, path: str, *, start: int | None = None, end: int | None = None) -> dict:
    target = repo / path
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    selected = lines[(start or 1) - 1 : end if end is not None else len(lines)]
    return {
        "ref": path,
        "kind": "evidence",
        "repo_id": str(repo),
        "path": path,
        "commit_sha": _git(repo, "rev-parse", "HEAD"),
        "blob_sha": _git(repo, "hash-object", path),
        "range_start": start,
        "range_end": end,
        "range_sha": hashlib.sha256("".join(selected).encode()).hexdigest() if start else None,
        "verified_at": "2026-09-02T00:00:00+00:00",
    }


def test_unchanged_blob_is_verified_current(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\ntwo\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(brain_home, "fact", "one", scope="global", sources=[_source(repo, "note.txt")])
    result = freshness.resolve(brain_home, mid, repo)
    assert result == {"state": "VERIFIED_CURRENT", "reason": "blob unchanged"}


def test_changed_blob_is_stale_and_dropped(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(brain_home, "fact", "one", scope="global", sources=[_source(repo, "note.txt")])
    (repo / "note.txt").write_text("changed\n", encoding="utf-8")
    result = freshness.resolve(brain_home, mid, repo)
    assert result["state"] == "STALE"


def test_no_sources_is_unknown(brain_home: Path) -> None:
    mid = semantic.add_memory(brain_home, "fact", "one", scope="global")
    assert freshness.resolve(brain_home, mid, brain_home)["state"] == "UNKNOWN"


def test_migration_adds_nullable_source_columns_idempotently(brain_home: Path) -> None:
    conn = db.connect(db.db_path(brain_home))
    cols_before = [r[1] for r in conn.execute("PRAGMA table_info(memory_sources)")]
    conn.close()
    assert db.migrate(db.db_path(brain_home)) == []
    conn = db.connect(db.db_path(brain_home))
    cols_after = [r[1] for r in conn.execute("PRAGMA table_info(memory_sources)")]
    conn.close()
    assert cols_before == cols_after
    assert {"repo_id", "path", "symbol", "commit_sha", "blob_sha", "range_start", "range_end", "range_sha", "verified_at"} <= set(cols_after)


def test_cache_detects_uncommitted_blob_change(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(
        brain_home, "fact", "one", scope="global", sources=[_source(repo, "note.txt")]
    )
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"
    (repo / "note.txt").write_text("changed\n", encoding="utf-8")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "STALE"


def test_cache_detects_evidence_added_at_same_head(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(brain_home, "fact", "one", scope="global")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "UNKNOWN"
    semantic.curate(brain_home, mid, sources=[_source(repo, "note.txt")])
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"


def test_renamed_path_is_source_moved(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "old.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(
        brain_home, "fact", "one", scope="global", sources=[_source(repo, "old.txt")]
    )
    (repo / "old.txt").rename(repo / "new.txt")
    _commit(repo, "rename")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "SOURCE_MOVED"


def test_no_sources_is_unknown_and_still_admitted_low(brain_home: Path) -> None:
    mid = semantic.add_memory(brain_home, "fact", "one", scope="global", grade="OBSERVED")
    row = semantic._row(brain_home, mid)
    assert row is not None
    intent = autoinject.RetrievalIntent(
        task_text="fact one",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="s",
    )
    item = autoinject._build_items(brain_home, [row])[0]
    assert freshness.resolve(brain_home, mid, brain_home)["state"] == "UNKNOWN"
    assert item.freshness == "UNKNOWN"
    assert item.confidence is contracts.Confidence.LOW


def test_capture_evidence_from_nested_cwd_uses_git_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (nested / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)

    captured = semantic.capture_evidence(nested, "note.txt")

    assert captured["repo_id"] == str(repo.resolve())
    assert captured["path"] == "nested/note.txt"
    assert captured["blob_sha"]


def test_capture_evidence_rejects_out_of_bounds_range(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    try:
        semantic.capture_evidence(repo, "note.txt:1-2")
    except Exception as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("out-of-bounds evidence range unexpectedly accepted")


def test_migration_guard_is_case_insensitive(tmp_path: Path) -> None:
    dbfile = tmp_path / "legacy.sqlite"
    conn = db.connect(dbfile)
    conn.execute("CREATE TABLE memory_sources (id INTEGER PRIMARY KEY, REPO_ID TEXT)")
    conn.execute("CREATE TABLE memories (memory_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_version VALUES (11, 'legacy')")
    conn.commit()
    conn.close()
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    source = Path(__file__).parents[1] / "src" / "second_brain" / "migrations" / "0012_evidence_freshness.sql"
    (migration_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    assert db.migrate(dbfile, migration_dir) == [12]
    conn = db.connect(dbfile)
    columns = {str(row["name"]).casefold() for row in conn.execute("PRAGMA table_info(memory_sources)")}
    conn.close()
    assert "repo_id" in columns and "verified_at" in columns


def test_freshness_failure_fails_open(brain_home: Path, monkeypatch) -> None:
    semantic.add_memory(brain_home, "failure fact", "failure fact", scope="global")
    monkeypatch.setattr(semantic, "_sources", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    intent = autoinject.RetrievalIntent(
        task_text="failure fact",
        project_id="proj-a",
        agent_id="a1",
        role_profile="worker",
        session_id="fail-open",
    )
    decision = autoinject.prepare_injection(brain_home, intent)
    assert decision.decision is contracts.InjectionDecision.NO_INJECTION
    assert decision.reason is contracts.NoInjectionReason.BRAIN_UNAVAILABLE


def test_verified_annotation_uses_matching_source(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "first.txt").write_text("first\n", encoding="utf-8")
    (repo / "second.txt").write_text("second\n", encoding="utf-8")
    _commit(repo)
    first = _source(repo, "first.txt")
    second = _source(repo, "second.txt")
    mid = semantic.add_memory(brain_home, "fact", "second", scope="global", sources=[first, second])
    (repo / "first.txt").write_text("changed\n", encoding="utf-8")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"
    assert freshness.current_source(brain_home, mid, repo)["path"] == "second.txt"


def test_cache_recomputes_after_edit_revert(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(
        brain_home, "fact", "one", scope="global", sources=[_source(repo, "note.txt")]
    )
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"
    (repo / "note.txt").write_text("changed\n", encoding="utf-8")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "STALE"
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"


def test_cache_recomputes_after_missing_source_restore(brain_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    _commit(repo)
    mid = semantic.add_memory(
        brain_home, "fact", "one", scope="global", sources=[_source(repo, "note.txt")]
    )
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"
    (repo / "note.txt").unlink()
    assert freshness.resolve(brain_home, mid, repo)["state"] == "SOURCE_MISSING"
    (repo / "note.txt").write_text("one\n", encoding="utf-8")
    assert freshness.resolve(brain_home, mid, repo)["state"] == "VERIFIED_CURRENT"
