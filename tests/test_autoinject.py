"""P0 AutoInject SHADOW pipeline (Phase 0C; plan §6.1-6.8, 6.11, 17.1 AutoInject).

Deterministic decision/packet/delivery tests: sparse injection, validity
gate (project/scope, superseded, contradiction), dedupe on active lineage,
budget caps, fail-open, migration 0008, and the `brainctl autoinject shadow`
CLI. SHADOW means: decide + record only, never mutate model context.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import autoinject, db, paths, semantic
from second_brain.contracts import (
    BrainDeliveryRecord,
    BrainInjectionDecision,
    BrainPacket,
    InjectionDecision,
    NoInjectionReason,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _add(
    home: Path,
    title: str,
    body: str,
    *,
    project_id: str | None = "proj-a",
    scope: str = "project",
    grade: str = "TESTED",
) -> str:
    return semantic.add_memory(
        home, title, body, scope=scope, project_id=project_id, grade=grade
    )


def _activate(home: Path, memory_id: str) -> None:
    semantic.curate(home, memory_id, status="current")


def _seed_current(home: Path, title: str, body: str, **kw) -> str:
    mid = _add(home, title, body, **kw)
    _activate(home, mid)
    return mid


def _inject(home: Path, task: str, **kw) -> BrainInjectionDecision:
    """Default BrainLifecycle prepare_injection for tests (proj-a, s1, main)."""
    session_id = kw.pop("session_id", "s1")
    branch_id = kw.pop("branch_id", "main")
    return autoinject.BrainLifecycle(home).prepare_injection(
        task,
        project_id=kw.pop("project_id", "proj-a"),
        agent_id=kw.pop("agent_id", "a1"),
        role_profile=kw.pop("role_profile", "worker"),
        session_id=session_id,
        branch_id=branch_id,
    )


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
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

def _make_brain(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal migrated Brain home (mirrors tests/conftest.make_brain)."""
    import shutil

    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SECOND_BRAIN_HOME", str(home))
    paths.ensure_layout(home)
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    cfg = home / "config"
    for name in paths.REQUIRED_CONFIG_FILES:
        (cfg / name).write_text("schema_version = 1\n", encoding="utf-8")
    shutil.copytree(REPO_ROOT / "templates", home / "templates", dirs_exist_ok=True)
    db.migrate(db.db_path(home))
    return home


def _delivery_rows(home: Path) -> list[dict]:
    conn = db.connect(db.db_path(home))
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM deliveries ORDER BY memory_id, memory_version"
            ).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sparse AutoInject: no memory, wrong project, unrelated project
# ---------------------------------------------------------------------------


def test_no_relevant_memory_yields_no_injection(brain_home) -> None:
    d = _inject(brain_home, "quantum entanglement of pasta shapes")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.NO_RELEVANT_MEMORY
    assert d.selected_ids == []
    assert d.packet_ref is None


def test_wrong_project_memory_not_injected(brain_home) -> None:
    _seed_current(brain_home, "WAL restore safety", "never leave -wal next to restored db")
    d = _inject(brain_home, "WAL restore safety", project_id="proj-b")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.WRONG_PROJECT
    assert d.selected_ids == []


def test_global_scope_memory_valid_for_any_project(brain_home) -> None:
    mid = _seed_current(
        brain_home, "Global law", "always verify before retry", scope="global", project_id=None
    )
    d = _inject(brain_home, "verify before retry", project_id="proj-b")
    assert d.decision is InjectionDecision.INJECT
    assert d.selected_ids == [mid]


# ---------------------------------------------------------------------------
# Canonical packet determinism + supersede deltas
# ---------------------------------------------------------------------------


def test_relevant_current_injects_deterministic_packet(brain_home) -> None:
    _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    a = _inject(brain_home, "migration ordering")
    b = _inject(brain_home, "migration ordering", branch_id="other-branch")
    assert a.decision is InjectionDecision.INJECT
    assert b.decision is InjectionDecision.INJECT
    assert a.packet_ref == b.packet_ref  # stable packet id for same content
    assert a.selected_ids == b.selected_ids


def test_superseded_never_current_and_delta_emitted(brain_home) -> None:
    mid = _seed_current(brain_home, "Retry policy", "retry once then fail")
    semantic.supersede(
        brain_home,
        mid,
        new_title="Retry policy v2",
        new_body="retry twice then fail",
        change_note="policy updated",
    )
    d = _inject(brain_home, "retry policy")
    assert d.decision is InjectionDecision.INJECT
    # The packet must reference v2 only and carry the supersede delta.
    packet = autoinject.render_packet(d)
    assert packet is not None
    assert f"ITEM {mid}@2" in packet
    assert f"UPDATE {mid} v2 supersedes {mid} v1" in packet
    assert f"ITEM {mid}@1" not in packet


def test_contradiction_withheld_per_policy(brain_home) -> None:
    _seed_current(brain_home, "Cache setting", "cache on")
    _seed_current(brain_home, "Cache setting", "cache off")
    d = _inject(brain_home, "cache setting")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.CONTRADICTORY_UNRESOLVED


# ---------------------------------------------------------------------------
# Delivery ledger: dedupe on lineage, branch independence
# ---------------------------------------------------------------------------


def test_dedupe_same_lineage_second_call_skips(brain_home) -> None:
    _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    first = _inject(brain_home, "migration ordering")
    assert first.decision is InjectionDecision.INJECT
    rows = _delivery_rows(brain_home)
    assert len(rows) == 1

    second = _inject(brain_home, "migration ordering")
    assert second.decision is InjectionDecision.NO_INJECTION
    assert second.reason is NoInjectionReason.ALREADY_DELIVERED
    assert len(_delivery_rows(brain_home)) == 1  # no duplicate rows

    third = _inject(brain_home, "migration ordering", branch_id="branch-b")
    assert third.decision is InjectionDecision.INJECT  # different branch delivers again
    assert len(_delivery_rows(brain_home)) == 2


def test_delivery_record_roundtrip_and_hash(brain_home) -> None:
    mid = _seed_current(brain_home, "Migration ordering", "apply migrations in numeric order")
    d = _inject(brain_home, "migration ordering")
    rows = _delivery_rows(brain_home)
    assert len(rows) == 1
    row = rows[0]
    assert row["memory_id"] == mid
    assert row["root_session_id"] == "s1"
    assert row["branch_id"] == "main"
    rec = BrainDeliveryRecord.from_dict(row)
    assert rec.delivery_id == row["delivery_id"]
    assert rec.canonical_hash == row["canonical_hash"]
    # canonical hash equals the stable per-item content hash (deterministic)
    packet = autoinject.render_packet(d)
    assert packet is not None
    item = BrainPacket.parse(packet).items[0]
    assert rec.canonical_hash == autoinject.item_canonical_hash(item)
    # same content on another branch -> identical packet + identical hash
    d2 = _inject(brain_home, "migration ordering", branch_id="branch-x")
    assert d2.decision is InjectionDecision.INJECT
    assert autoinject.render_packet(d2) == packet


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_hard_cap_never_exceeded(brain_home, monkeypatch) -> None:
    _seed_current(
        brain_home,
        "Huge memory",
        "word " * 4000,  # ~4000 words -> far above any cap in tokens
    )
    monkeypatch.setenv("SECOND_BRAIN_AUTOINJECT_HARD_CAP_TOKENS", "200")
    d = _inject(brain_home, "huge memory")
    assert d.decision is InjectionDecision.INJECT or d.decision is InjectionDecision.NO_INJECTION
    if d.decision is InjectionDecision.INJECT:
        assert d.packet_token_size is not None and d.packet_token_size <= 200
        assert autoinject.render_packet(d) != ""  # truncated packet still renders


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------


def test_fail_open_retrieval_error(brain_home, monkeypatch) -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("retrieval exploded")

    monkeypatch.setattr(semantic, "search_memories", boom)
    d = _inject(brain_home, "any task")
    assert d.decision is InjectionDecision.NO_INJECTION
    assert d.reason is NoInjectionReason.BRAIN_UNAVAILABLE
    assert d.packet_ref is None


# ---------------------------------------------------------------------------
# Migration 0008: fresh, v7 upgrade, idempotent
# ---------------------------------------------------------------------------


def test_migration_0008_fresh_and_v7_upgrade(tmp_path, monkeypatch) -> None:
    # Fresh db: v8 with deliveries table.
    home = tmp_path / "fresh"
    _make_brain(home, monkeypatch)
    conn = db.connect(db.db_path(home))
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 8
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "deliveries" in tables
    finally:
        conn.close()

    # v7 db: apply only 0001..0007, then migrate with the real chain.
    home7 = tmp_path / "v7"
    migs7 = tmp_path / "migs7"
    migs7.mkdir()
    real = db.MIGRATIONS_DIR
    for p in sorted(real.glob("*.sql"))[:7]:
        (migs7 / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migs7)
    _make_brain(home7, monkeypatch)
    conn = db.connect(db.db_path(home7))
    try:
        v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
        assert v == 7
    finally:
        conn.close()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real)
    assert db.migrate(db.db_path(home7)) == [8]  # applies exactly 0008
    assert db.migrate(db.db_path(home7)) == []  # idempotent second run
    conn = db.connect(db.db_path(home7))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "deliveries" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(deliveries)")}
        assert {
            "delivery_id",
            "root_session_id",
            "agent_session_id",
            "branch_id",
            "memory_id",
            "memory_version",
            "canonical_hash",
            "packet_id",
            "delivered_event_id",
            "delivered_at",
            "superseded_by_delivery_id",
        } <= cols
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI: brainctl autoinject shadow --json
# ---------------------------------------------------------------------------


def test_cli_shadow_json_deterministic_and_dedupe(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    _seed_current(home, "Migration ordering", "apply migrations in numeric order")

    args = [
        "autoinject",
        "shadow",
        "--task",
        "migration ordering",
        "--project",
        "proj-a",
        "--session",
        "s1",
        "--agent",
        "a1",
        "--role",
        "worker",
        "--json",
    ]
    r1 = _run_cli(home, *args)
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert out1["decision"] == "INJECT"
    assert out1["reason"] is None
    assert out1["packet"].startswith("[BRAIN_CONTEXT_DELTA v1]")
    assert out1["delivery_id"]
    assert out1["candidate_ids"] == out1["selected_ids"]

    # Same lineage: second call dedupes -> NO_INJECTION, still exit 0.
    r2 = _run_cli(home, *args)
    assert r2.returncode == 0, r2.stderr
    out2 = json.loads(r2.stdout)
    assert out2["decision"] == "NO_INJECTION"
    assert out2["reason"] == "ALREADY_DELIVERED"
    assert out2["packet"] is None

    # Fresh lineage: same task -> byte-identical packet (determinism).
    r3 = _run_cli(home, *args, "--session", "s2", "--branch", "b2")
    out3 = json.loads(r3.stdout)
    assert out3["decision"] == "INJECT"
    assert out3["packet"] == out1["packet"]
    assert out3["candidate_ids"] == out1["candidate_ids"]


def test_cli_unknown_project_no_injection_not_crash(tmp_path) -> None:
    home = tmp_path / "brain"
    home.mkdir()
    r = _run_cli(home, "init")
    assert r.returncode == 0, r.stderr
    _seed_current(home, "Migration ordering", "apply migrations in numeric order")
    r = _run_cli(
        home,
        "autoinject",
        "shadow",
        "--task",
        "migration ordering",
        "--project",
        "proj-zzz",
        "--session",
        "s1",
        "--agent",
        "a1",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["decision"] == "NO_INJECTION"
    assert out["reason"] in ("WRONG_PROJECT", "NO_RELEVANT_MEMORY")
