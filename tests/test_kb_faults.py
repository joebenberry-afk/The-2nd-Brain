"""V3 core: fault injection (ARCH-03 bounded failure, MEM-05 durability).

Derived state heals; canonical state is never silently lost; a failure the Brain cannot repair
is reported, never answered as "nothing found".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from second_brain.kb import doctor, hooks, index, records, views
from second_brain.kb.records import Record


def _saved(home: Path, **kw: object) -> Record:
    base: dict[str, object] = {
        "id": records.new_id(),
        "title": "Calibrate the widget sensor",
        "scope": "global",
        "status": "current",
        "grade": "TESTED",
        "recorded_at": "2026-09-01T00:00:00+00:00",
    }
    base.update(kw)
    rec = Record(**base)  # type: ignore[arg-type]
    records.save(home, rec)
    return rec


def test_corrupted_index_is_rebuilt_from_the_files(tmp_path: Path) -> None:
    rec = _saved(tmp_path)
    assert index.search(tmp_path, "widget sensor", None)
    index.index_path(tmp_path).write_bytes(b"this is not a database" * 100)
    hits = index.search(tmp_path, "widget sensor", None)
    assert [h.record.id for h in hits] == [rec.id]


def test_deleted_index_is_rebuilt(tmp_path: Path) -> None:
    rec = _saved(tmp_path)
    index.search(tmp_path, "widget", None)
    index.index_path(tmp_path).unlink()
    assert [h.record.id for h in index.search(tmp_path, "widget", None)] == [rec.id]


def test_a_locked_index_is_an_error_not_an_empty_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved(tmp_path)
    index.refresh(tmp_path)
    monkeypatch.setattr(index, "LOCK_TIMEOUT_S", 0.1)
    holder = sqlite3.connect(index.index_path(tmp_path))
    holder.execute("BEGIN EXCLUSIVE")
    try:
        records.save(
            tmp_path, records.replace(_saved(tmp_path, title="Another widget"), title="x y")
        )
        with pytest.raises(sqlite3.OperationalError):
            index.search(tmp_path, "widget", None)
    finally:
        holder.rollback()
        holder.close()


def test_a_broken_record_file_is_reported_and_the_rest_still_serve(tmp_path: Path) -> None:
    good = _saved(tmp_path)
    (records.records_dir(tmp_path) / "mem-000000000bad.md").write_text("---\nid: x\n", "utf-8")
    assert [h.record.id for h in index.search(tmp_path, "widget", None)] == [good.id]
    assert any("mem-000000000bad" in e for e in doctor.check(tmp_path).errors)


def test_crash_between_the_two_supersede_writes_is_detected(tmp_path: Path) -> None:
    old = _saved(tmp_path, title="Old way")
    new = _saved(tmp_path, title="New way")
    # Simulate the crash: the replacement was written, the old record was not.
    records.save(tmp_path, records.replace(new, supersedes=(old.id,)))
    warnings = doctor.check(tmp_path).warnings
    assert any("still active" in w and old.id in w for w in warnings)


def test_hooks_stay_silent_on_corrupt_views(tmp_path: Path) -> None:
    _saved(tmp_path, type="correction", trigger_errors=("boom",))
    views.compile_views(tmp_path)
    (tmp_path / "views" / "_none" / "corrections.json").write_text("{not json", "utf-8")
    payload = {"hook_event_name": "PostToolUseFailure", "error": "boom"}
    # A corrupt compiled table falls back to nothing rather than raising into the host.
    try:
        out = hooks.handle(tmp_path, payload)
    except json.JSONDecodeError:
        pytest.fail("a corrupt view must not raise into the host")
    assert "Brain correction" in out["hookSpecificOutput"]["additionalContext"]


def test_interrupted_atomic_write_leaves_the_old_record(tmp_path: Path, monkeypatch) -> None:
    rec = _saved(tmp_path, title="Stable title")

    def boom(*_args: object, **_kw: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(records.os, "replace", boom)
    with pytest.raises(OSError):
        records.save(tmp_path, records.replace(rec, title="Half written"))
    monkeypatch.undo()
    assert records.load(tmp_path, rec.id).title == "Stable title"
    assert not list(records.records_dir(tmp_path).glob(".*.tmp"))
